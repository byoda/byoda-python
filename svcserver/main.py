'''
API server for Bring Your Own Data and Algorithms

To run this service in a test environment:
- mkdir /tmp/byoda-tests/svcserver/
- cd /tmp/byoda-tests/svcserver/
- cp -r ~/src/byoda-python/tests/collateral/local/addressbook-service/* .
- cd network-byoda.net/services/service-4294929430/
- scp azureuser@dir.byoda.net:/opt/byoda/dirserver/network-byoda.net/services/service-4294929430/service-contract.json .

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os
import sys
import yaml

from contextlib import asynccontextmanager

from fastapi import FastAPI

from byoda.util.fastapi import setup_api

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema

from byoda.datastore.document_store import DocumentStoreType

from byoda.datatypes import CloudType

from byoda.servers.service_server import ServiceServer

from byoda.util.paths import Paths

from byoda.util.logger import Logger

from byoda import config

from .routers import service as ServiceRouter
from .routers import member as MemberRouter
from .routers import search as SearchRouter
from .routers import status as StatusRouter
from .routers import app as AppRouter

_LOGGER = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_file: str = os.environ.get('CONFIG_FILE', 'config.yml')
    with open(config_file) as file_desc:
        server_config: dict[str, str | int | bool | None] = yaml.safe_load(
            file_desc
        )

    debug: bool = server_config['application']['debug']
    verbose: bool = not debug

    global _LOGGER
    _LOGGER = Logger.getLogger(
        sys.argv[0], debug=debug, verbose=verbose,
        logfile=server_config['svcserver'].get('logfile')
    )
    _LOGGER.debug(f'Read configuration file: {config_file}')

    network = Network(
        server_config['svcserver'], server_config['application']
    )

    network.paths = Paths(
        network=network.name,
        root_directory=server_config['svcserver']['root_dir']
    )

    if not os.environ.get('SERVER_NAME') and network.name:
        os.environ['SERVER_NAME'] = network.name

    _LOGGER.debug('Going to set up service server')
    server: ServiceServer = await ServiceServer.setup(network, server_config)
    _LOGGER.debug('Setup service server completed')

    config.server = server
    service: Service = server.service

    _LOGGER.debug('Setting up document store')
    await server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType.LOCAL,
        private_bucket='byoda',
        restricted_bucket='byoda',
        public_bucket='byoda',
        root_dir=server_config['svcserver']['root_dir']
    )

    _LOGGER.debug('Loading network secrets')
    await server.load_network_secrets()

    _LOGGER.debug('Setting up service secrets')
    await server.load_secrets(
        server_config['svcserver']['private_key_password']
    )

    _LOGGER.debug('Loading schema')
    await server.load_schema()
    schema: Schema = service.schema
    schema.get_data_classes(with_pubsub=False)

    _LOGGER.debug('Generating data models')
    schema.generate_data_models('svcserver/codegen', datamodels_only=True)

    await server.setup_asset_cache(
        server_config['svcserver']['asset_cache'],
        server_config['svcserver']['asset_cache_readwrite']
    )
    _LOGGER.debug('Registering service')
    await server.service.register_service()

    _LOGGER.debug('Lifespan startup complete')

    config.trace_server = server_config['application'].get(
        'trace_server', config.trace_server
    )

    yield

    _LOGGER.info('Shutting down server')


config_file: str = os.environ.get('CONFIG_FILE', 'config.yml')
with open(config_file) as file_desc:
    server_config: dict[str, str | int | bool | None] = yaml.safe_load(
        file_desc
    )

app: FastAPI = setup_api(
    'BYODA service server', 'A server hosting a service in a BYODA '
    'network', 'v0.0.1',
    [
        ServiceRouter,
        MemberRouter,
        SearchRouter,
        StatusRouter,
        AppRouter,
    ],
    lifespan=lifespan, trace_server=config.trace_server,
    cors=server_config['svcserver']['cors_origins']
)

config.app = app
