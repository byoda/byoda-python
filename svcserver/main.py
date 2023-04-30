'''
API server for Bring Your Own Data and Algorithms

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import yaml

from byoda.util.fastapi import setup_api, add_cors

from byoda.util.logger import Logger
from byoda import config

from byoda.datamodel.network import Network

from byoda.datastore.document_store import DocumentStoreType

from byoda.storage.filestorage import FileStorage

from byoda.servers.service_server import ServiceServer

from .routers import service as ServiceRouter
from .routers import member as MemberRouter
from .routers import search as SearchRouter
from .routers import status as StatusRouter

_LOGGER = None

config_file = os.environ.get('CONFIG_FILE', 'config.yml')
with open(config_file) as file_desc:
    app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

app = setup_api(
    'BYODA service server', 'A server hosting a service in a BYODA '
    'network', 'v0.0.1', [],
    [ServiceRouter, MemberRouter, SearchRouter, StatusRouter]
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

    network = Network(
        app_config['svcserver'], app_config['application']
    )
    network.paths.storage_driver = await FileStorage.setup([
        'svcserver']['root_dir']
    )

    if not os.environ.get('SERVER_NAME') and config.server.network.name:
        os.environ['SERVER_NAME'] = config.server.network.name

    config.server = ServiceServer(network, app_config)

    await config.server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=None,
        bucket_prefix=None,
        root_dir=app_config['svcserver']['root_dir']
    )

    await config.server.load_network_secrets()

    await config.server.load_secrets(
        app_config['svcserver']['private_key_password']
    )
    await config.server.load_schema()

    await config.server.service.register_service()

    add_cors(app, app_config['svcserver']['cors_origins'])
