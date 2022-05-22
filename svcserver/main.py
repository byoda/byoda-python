'''
API server for Bring Your Own Data and Algorithms

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import yaml

from byoda.util.fastapi import setup_api

from byoda.util.logger import Logger
from byoda import config

from byoda.servers.service_server import ServiceServer

from .routers import service
from .routers import member
from .routers import search

_LOGGER = None

config_file = os.environ.get('CONFIG_FILE', 'config.yml')
with open(config_file) as file_desc:
    app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

app = setup_api(
    'BYODA service server', 'A server hosting a service in a BYODA '
    'network v0.0.1',
    app_config['cors_origins'], [service, member, search]
)


@app.on_event('startup')
async def setup():
    config_file = os.environ.get('CONFIG_FILE', 'config.yml')
    with open(config_file) as file_desc:
        app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    debug = app_config['application']['debug']
    verbose = not debug
    _LOGGER = Logger.getLogger(
        sys.argv[0], debug=debug, verbose=verbose,
        logfile=app_config['svcserver'].get('logfile')
    )
    _LOGGER.debug(f'Read configuration file: {config_file}')

    if not os.environ.get('SERVER_NAME') and config.server.network.name:
        os.environ['SERVER_NAME'] = config.server.network.name

    config.server = ServiceServer(app_config)
    await config.server.load_network_secrets()

    await config.server.load_secrets(
        app_config['svcserver']['private_key_password']
    )
    await config.server.load_schema()

    await config.server.service.register_service()
