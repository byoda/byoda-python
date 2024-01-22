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
    def __init__(self, config_block: str, filepath: str = None,
                 is_worker: bool = False) -> None:
        if not filepath:
            filepath: str = os.environ.get('CONFIG_FILE', 'config.yml')

        with open(filepath) as file_desc:
            config: dict[str, str | int | bool] = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        self.server_config: dict = config[config_block]
        self.app_config: dict = config['application']

        self.loglevel: str = self.server_config.get('loglevel', 'INFO')
        if is_worker:
            self.logfile: str = self.server_config.get('worker_logfile')
        else:
            self.logfile: str = self.server_config.get('logfile')

        debug_setting: str = self.app_config.get('debug')
        self.debug: bool = False
        if isinstance(debug_setting, bool):
            self.debug = debug_setting
        elif debug_setting and debug_setting.lower() != 'false':
            self.debug = True
