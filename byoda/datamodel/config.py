'''
Class for modeling the configuration of a server

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import os
import yaml

from logging import getLogger

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)


class ServerConfig:
    '''
    Configuration class for all components except the pod. Config file format:
      application:
        debug: bool
        loglevel: str
        worker_loglevel: str
        environment: str['dev', 'test', 'prod']
        network: str
        trace_server: str
        trace_port: int

      {dir,svc,app}server:
        name: str
        root_dir: str
        logfile: str
        worker_logfile: str
        roles: list[str]
        private_key_password: str
        service_id: int
        cors_origins: list[str]
        fqdn: str               # used by appserver
        app_id: UUID            # used by appserver
        cache: str              # used by appserver
        dnsdb: str              # only for dirserver and byohost.host_server
        member_cache: str       # only for svc{server, worker}
        asset_cache: str        # only for svc{server, worker}
    '''

    def __init__(self, config_block: str, filepath: str = None,
                 is_worker: bool = False) -> None:
        '''
        Unifies reading the config.yml file for the server configuration.
        This class is called before logging is setup so can't send
        log messages
        '''

        # path to config file
        self.filepath: str
        if not filepath:
            self.filepath = os.environ.get('CONFIG_FILE', 'config.yml')
        else:
            self.filepath = filepath

        with open(self.filepath) as file_desc:
            self.raw_config: dict[str, str | int | bool] = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        self.server_config: dict = self.raw_config[config_block]
        self.app_config: dict = self.raw_config['application']

        self.logfile: str = self.server_config.get('logfile')
        self.loglevel: str = self.app_config.get('loglevel', 'INFO')

        # Are we an application server or a workr
        self.is_worker: bool = is_worker
        if is_worker:
            self.loglevel: str = self.app_config.get(
                'worker_loglevel', self.loglevel
            )
            self.logfile: str = self.server_config.get(
                'worker_logfile', self.logfile
            )

        # Debug should be set as YAML bool (ie. True or False) but we take
        # strings as well. All strings except string.lower 'false' are
        # considered True
        debug_setting: str = self.app_config.get('debug')
        self.debug: bool = False
        if isinstance(debug_setting, bool):
            self.debug = debug_setting
        elif debug_setting and debug_setting.lower() != 'false':
            self.debug = True
