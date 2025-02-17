'''
Bootstrap the account for a pod

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os

from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger
from abc import ABC
from abc import abstractmethod

from jinja2 import Template

from byoda.datatypes import IdType


_LOGGER: Logger = getLogger(__name__)

ANGIE_SITE_CONFIG_DIR: str = '/etc/angie/conf.d'
ANGIE_PID_FILE: str = '/run/angie.pid'


class TargetConfig(ABC):
    '''
    TargetConfig is an abstract base class that describes a target
    configuration and provides methods to check whether the the target
    configuration is in place, and if not, methods to implement the
    target configuration
    '''
    @abstractmethod
    def __init__(self):
        return NotImplementedError

    @abstractmethod
    def exists(self):
        return NotImplementedError

    @abstractmethod
    def create(self):
        return NotImplementedError


class AngieConfig(TargetConfig):
    def __init__(self, directory: str, filename: str, identifier: UUID,
                 subdomain: str, cert_filepath: str, key_filepath: str,
                 alias: str, network: str, public_cloud_endpoint: str,
                 restricted_cloud_endpoint: str, private_cloud_endpoint: str,
                 cloud: str, port: int, service_id: int = None,
                 root_dir: str = '/byoda', host_root_dir: str = '/byoda',
                 custom_domain: str = None, shared_webserver: bool = False,
                 public_bucket: str = None, restricted_bucket: str = None,
                 private_bucket: str = None) -> None:
        '''
        Manages angie configuration files for virtual servers

        :param directory: location of the template and final angie
        configuration file
        :param filename: name of the angie configuration file to be
        created
        :param identifier: either the account_id or the member_id
        :param subdomain: subdomain of the CN for the cert
        :param cert_filepath: location of the public cert for the CN
        :param key_filepath: location of the unencrypted private key
        :param alias: alias for the account or membership
        :param network: name of the joined network
        :param public_cloud_endpoint: URL for the endpoint of the
        public bucket
        :param restricted_cloud_endpoint: URL for the endpoint of the
        private bucket
        :param private_cloud_endpoint: URL for the endpoint of the
        private bucket
        :param cloud: cloud the pod is running on, used for locations proxying
        to storage
        :param port: the http port for the virtual server
        :param service_id: service ID for the membership, if applicable
        :param http_port: the http port for the virtual server to listen on
        :param custom_domain: a custom domain to use for the virtual server
        :param shared_webserver: set to False if the angie service is only
        used for the podserver, set to True if an angie server outside
        of the pod is used.
        :param public_bucket: the FQDN for the AWS/GCP bucket or Azure storage
        :param restricted_bucket: the FQDN for the AWS/GCP bucket or Azure
        storage
        :param private_bucket: the FQDN for the AWS/GCP bucket or Azure storage
        account
        '''

        self.identifier: str = str(identifier)
        self.subdomain: str = subdomain
        self.service_id: int = service_id
        self.alias: str = alias
        self.network: str = network
        self.public_cloud_endpoint: str = public_cloud_endpoint
        self.restricted_cloud_endpoint: str = restricted_cloud_endpoint
        self.private_cloud_endpoint: str = private_cloud_endpoint
        self.cloud: str = cloud
        self.directory: str = directory
        self.filename: str = filename
        self.root_dir: str = root_dir
        self.port: int = port
        self.custom_domain: str = custom_domain
        self.shared_webserver: bool = shared_webserver
        self.public_bucket: str = public_bucket
        self.restricted_bucket: str = restricted_bucket
        self.private_bucket: str = private_bucket

        self.hostname: str
        self.root_dir: str
        if self.shared_webserver:
            # We are running on shared infrastructure, so no dedicated angie
            # or postgres pods dedicated
            self.hostname = 'localhost'
            # Use the actual root_directory for the pod on the host running
            # the container
            self.root_dir = host_root_dir
        else:
            # There is a pod with containers for angie, byoda and postgres
            self.hostname = 'byoda'
            self.root_dir = root_dir

        self.cert_filepath: str = host_root_dir + cert_filepath[len(root_dir):]
        self.key_filepath: str = key_filepath

        self.config_filepath: str
        if self.subdomain == IdType.ACCOUNT.value:
            self.config_filepath = f'{directory}/account.conf'
        else:
            self.config_filepath = f'{directory}/member-{identifier}.conf'

        self.template_filepath: str = f'{directory}/{filename}' + '.jinja2'

    def exists(self) -> bool:
        '''
        Does the Angie configuration file already exist?
        '''

        return os.path.exists(self.config_filepath)

    def create(self) -> None:
        '''
        Creates the angie virtual server configuration file.
        The username is the first
        substring of the identifier, up to but not including the first
        '-'.
        '''

        _LOGGER.debug(
            f'Rendering template {self.template_filepath} '
            f'to {self.config_filepath}'
        )

        try:
            with open(self.template_filepath) as file_desc:
                templ = Template(file_desc.read())
        except FileNotFoundError:
            filepath = 'podserver/files/virtualserver.conf.jinja2'
            with open(filepath) as file_desc:
                templ = Template(file_desc.read())

        output: str = templ.render(
            identifier=str(self.identifier),
            subdomain=self.subdomain,
            cert_filepath=self.cert_filepath,
            key_filepath=self.key_filepath,
            alias=self.alias,
            network=self.network,
            public_cloud_endpoint=self.public_cloud_endpoint,
            restricted_cloud_endpoint=self.restricted_cloud_endpoint,
            private_cloud_endpoint=self.private_cloud_endpoint,
            cloud=self.cloud,
            root_dir=self.root_dir,
            service_id=self.service_id,
            port=self.port,
            custom_domain=self.custom_domain,
            shared_webserver=self.shared_webserver,
            public_bucket=self.public_bucket,
            restricted_bucket=self.restricted_bucket,
            private_bucket=self.private_bucket,
            hostname=self.hostname,
        )

        _LOGGER.debug(
            f'Writing angie configuration file {self.config_filepath}'
        )
        with open(self.config_filepath, 'w') as file_desc:
            file_desc.write(output)
