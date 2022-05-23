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

from byoda.servers.directory_server import DirectoryServer

from byoda.datamodel.network import Network

from .routers import account
from .routers import service
from .routers import member
from .routers import status

_LOGGER = None

app = setup_api(
    'BYODA directory server', 'The directory server for a BYODA network',
    'v0.0.1', [], [account, service, member, status]
)


@app.on_event('startup')
async def setup():
    with open('config.yml') as file_desc:
        app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    debug = app_config['application']['debug']
    verbose = not debug
    global _LOGGER
    _LOGGER = Logger.getLogger(
        sys.argv[0], debug=debug, verbose=verbose,
        logfile=app_config['dirserver'].get('logfile')
    )

    network = Network(
        app_config['dirserver'], app_config['application']
    )
    await network.load_network_secrets()
    server = DirectoryServer(network)
    await server.connect_db(app_config['dirserver']['dnsdb'])

    config.server = server

    await server.get_registered_services()
    await server.load_secrets()

    if not os.environ.get('SERVER_NAME') and config.server.network.name:
        os.environ['SERVER_NAME'] = config.server.network.name
