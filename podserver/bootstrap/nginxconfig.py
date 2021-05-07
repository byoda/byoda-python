'''
Bootstrap the account for a pod

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import signal
import logging
from uuid import UUID

from jinja2 import Template

from byoda.datatypes import IdType
from .targetconfig import TargetConfig

_LOGGER = logging.getLogger(__name__)

NGINX_SITE_CONFIG_DIR = '/etc/nginx/conf.d/'
NGINX_PID_FILE = '/run/nginx.pid'

class NginxConfig(TargetConfig):
    def __init__(self, directory: str, filename: str, identifier: UUID,
                 id_type: IdType, alias: str, network: str, bucket: str):
        '''
        Manages nginx configuration files for virtual servers

        :param identifier: either the account_id or the member_id
        :param id_type: either IdType.ACCOUNT or IdType.MEMBERSHIP
        :param alias: alias for the account or membership
        :param network: name of the joined network
        :param directory: location of the template and final nginx
        configuration file
        :param filename: name of the nginx configuration file to be
        created
        '''

        self.identifier = identifier
        self.id_type = id_type
        self.alias = alias
        self.network = network
        self.bucket = bucket
        self.directory = directory
        self.filename = filename

        self.config_filepath = f'{directory}/{filename}'
        self.template_filepath = f'{directory}/{filename}' + '.jinja2'

    def exists(self) -> bool:
        '''
        Does the Nginx configuration file already exist?
        '''

        return os.path.exists(self.config_filepath)

    def create(self):
        '''
        Creates the nginx virtual server configuration file
        '''

        _LOGGER.debug('Rendering template %s', self.template_filepath)
        with open(self.template_filepath) as file_desc:
            templ = Template(file_desc.read())

        output = templ.render(
            identifier=self.identifier,
            id_type=self.id_type.value,
            alias=self.alias,
            network=self.network,
            bucket=self.bucket
        )
        with open(self.config_filepath, 'w') as file_desc:
            file_desc.write(output)

    def reload(self):
        '''
        Reload the nginx process, if it is running
        '''

        try:
            with open(NGINX_PID_FILE) as file_desc:
                pid = int(file_desc.readline().strip())

            os.kill(pid, signal.SIGHUP)
            _LOGGER.debug('Sent SIGHUB to nginx process with pid %s', pid)
        except FileNotFoundError:
            _LOGGER.debug('Unable to read NGINX pid file: %s', NGINX_PID_FILE)
