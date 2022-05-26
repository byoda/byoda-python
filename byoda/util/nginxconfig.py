'''
Bootstrap the account for a pod

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import signal
import logging
from uuid import UUID
from abc import ABC, abstractmethod
from htpasswd.basic import UserExists

from jinja2 import Template

import htpasswd

from byoda.datatypes import IdType


_LOGGER = logging.getLogger(__name__)

NGINX_SITE_CONFIG_DIR = '/etc/nginx/conf.d'
NGINX_PID_FILE = '/run/nginx.pid'

HTACCESS_FILE = '/etc/nginx/htaccess.db'


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


class NginxConfig(TargetConfig):
    def __init__(self, directory: str, filename: str, identifier: UUID,
                 subdomain: str, cert_filepath: str, key_filepath: str,
                 alias: str, network: str, public_cloud_endpoint: str,
                 private_cloud_endpoint: str,
                 port: int, service_id: int = None, root_dir: str = '/byoda'):
        '''
        Manages nginx configuration files for virtual servers

        :param identifier: either the account_id or the member_id
        :param subdomain: subdomain of the CN for the cert
        :param cert_filepath: location of the public cert for the CN
        :param key_filepath: location of the unencrypted private key
        :param alias: alias for the account or membership
        :param network: name of the joined network
        :param directory: location of the template and final nginx
        configuration file
        :param filename: name of the nginx configuration file to be
        created
        :param public_cloud_endpoint: FQDN for the endpoint of the
        public bucket
        :param private_cloud_endpoint: FQDN for the endpoint of the
        private bucket
        :param service_id: service ID for the membership, if applicable
        '''

        self.identifier: str = str(identifier)
        self.subdomain: str = subdomain
        self.service_id: int = service_id
        self.alias: str = alias
        self.cert_filepath: str = cert_filepath
        self.key_filepath: str = key_filepath
        self.network: str = network
        self.public_cloud_endpoint: str = public_cloud_endpoint
        self.private_cloud_endpoint: str = private_cloud_endpoint
        self.directory: str = directory
        self.filename: str = filename
        self.root_dir: str = root_dir
        self.port: int = port

        if self.subdomain == IdType.ACCOUNT.value:
            self.config_filepath = f'{directory}/account.conf'
        else:
            self.config_filepath = f'{directory}/member-{identifier}.conf'

        self.template_filepath = f'{directory}/{filename}' + '.jinja2'

    def exists(self) -> bool:
        '''
        Does the Nginx configuration file already exist?
        '''

        return os.path.exists(self.config_filepath)

    def create(self, htaccess_password: str = 'byoda'):
        '''
        Creates the nginx virtual server configuration file. Also
        creates a 'htaccess' file that restricts access to the
        /logs folder on the virtual server. The username is the first
        substring of the identifier, up to but not including the first
        '-'.
        '''

        _LOGGER.debug('Rendering template %s', self.template_filepath)
        try:
            with open(self.template_filepath) as file_desc:
                templ = Template(file_desc.read())
        except FileNotFoundError:
            filepath = 'podserver/files/virtualserver.conf.jinja2'
            with open(filepath) as file_desc:
                templ = Template(file_desc.read())

        output = templ.render(
            identifier=str(self.identifier),
            subdomain=self.subdomain,
            cert_filepath=self.cert_filepath,
            key_filepath=self.key_filepath,
            alias=self.alias,
            network=self.network,
            public_cloud_endpoint=self.public_cloud_endpoint,
            private_cloud_endpoint=self.private_cloud_endpoint,
            root_dir=self.root_dir,
            service_id=self.service_id,
            port=self.port
        )
        with open(self.config_filepath, 'w') as file_desc:
            file_desc.write(output)

        if self.subdomain == IdType.ACCOUNT.value:
            # We also create a htpasswd file
            if not os.path.exists(HTACCESS_FILE):
                # Create an empty HTACCESS file
                open(HTACCESS_FILE, 'w')

            with htpasswd.Basic(HTACCESS_FILE, mode='md5') as userdb:
                try:
                    username = self.identifier.split('-')[0]
                    userdb.add(username, htaccess_password)
                except UserExists:
                    pass
            _LOGGER.debug('Created htaccess.db file')

    def reload(self):
        '''
        Reload the nginx process, if it is running
        '''

        try:
            with open(NGINX_PID_FILE) as file_desc:
                try:
                    pid = int(file_desc.readline().strip())
                    os.kill(pid, signal.SIGHUP)
                    _LOGGER.debug(
                        'Sent SIGHUP to nginx process with pid %s', pid
                    )
                except ValueError:
                    # No valid value in pid file means that nginx is not
                    # running, which can happen on a dev workstation
                    _LOGGER.warning('Could not find pid of nginx process')

        except FileNotFoundError:
            _LOGGER.debug('Unable to read NGINX pid file: %s', NGINX_PID_FILE)
