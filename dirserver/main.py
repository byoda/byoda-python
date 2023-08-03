'''
API server for Bring Your Own Data and Algorithms

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import yaml

from byoda.datamodel.network import Network

from byoda.datastore.document_store import DocumentStoreType

from byoda.datatypes import CloudType

from byoda.servers.directory_server import DirectoryServer

from byoda.util.fastapi import setup_api

from byoda.util.logger import Logger

from byoda import config

from .routers import account as AccountRouter
from .routers import service as ServiceRouter
from .routers import member as MemberRouter
from .routers import status as StatusRouter

_LOGGER = None

app = setup_api(
    'BYODA directory server', 'The directory server for a BYODA network',
    'v0.0.1', [],
    [AccountRouter, ServiceRouter, MemberRouter, StatusRouter],
    lifespan=None
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
    server = DirectoryServer(network)

    await server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType.LOCAL,
        private_bucket='byoda',
        restricted_bucket='byoda',
        public_bucket='byoda',
        root_dir=app_config['dirserver']['root_dir']
    )

    config.server = server

    await network.load_network_secrets()

    await server.connect_db(app_config['dirserver']['dnsdb'])

    await server.get_registered_services()
    await server.load_secrets()

    if not os.environ.get('SERVER_NAME') and config.server.network.name:
        os.environ['SERVER_NAME'] = config.server.network.name
