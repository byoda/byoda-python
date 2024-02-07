'''
Proof of Concept moderation server for Bring Your Own Data and Algorithms

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import yaml

from typing import Generator

from contextlib import asynccontextmanager

from fastapi import FastAPI

from byoda.datamodel.network import Network

from byoda.datastore.document_store import DocumentStoreType

from byoda.datatypes import CloudType
from byoda.datatypes import ClaimStatus
from byoda.datatypes import AppType

from byoda.servers.app_server import AppServer

from byoda.util.fastapi import setup_api

from byoda.util.logger import Logger

from byoda import config

from .routers import status as StatusRouter
from .routers import moderate as ModerateRouter
from .routers import cdn as CdnRouter
_LOGGER = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> Generator[None, any, None]:
    config_file: str = os.environ.get('CONFIG_FILE', 'config.yml')
    with open(config_file) as file_desc:
        app_config: dict[str, any] = yaml.load(
            file_desc, Loader=yaml.SafeLoader
        )

    debug: str = app_config['application']['debug']
    verbose: bool = not bool(debug)
    global _LOGGER
    _LOGGER = Logger.getLogger(
        sys.argv[0], debug=debug, verbose=verbose,
        logfile=app_config['appserver'].get('logfile')
    )

    app_type: AppType = AppType(app_config['appserver']['app_type'])

    routers: list = [StatusRouter]

    if app_type == AppType.CDN:
        routers.append(CdnRouter)
    elif app_type == AppType.MODERATE:
        routers.append(ModerateRouter)
    else:
        raise ValueError(f'Unknown app type {app_type}')

    network = Network(
        app_config['appserver'], app_config['application']
    )

    server = AppServer(
        app_type, app_config['appserver']['app_id'], network, app_config,
        routers
    )

    await server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType.LOCAL,
        private_bucket='byoda',
        restricted_bucket='byoda',
        public_bucket='byoda',
        root_dir=app_config['appserver']['root_dir']
    )

    config.server = server

    await network.load_network_secrets()

    await server.load_secrets(
        password=app_config['appserver']['private_key_password']
    )

    if not os.environ.get('SERVER_NAME') and config.server.network.name:
        os.environ['SERVER_NAME'] = config.server.network.name

    _LOGGER.debug('Lifespan startup complete')

    if config.trace_server:
        config.trace_server = app_config['application'].get(
            'trace_server', config.trace_server
        )

    yield

    _LOGGER.info('Shutting down server')


# eeks, we need to do this before we import the routers
_config_file: str = os.environ.get('CONFIG_FILE', 'config.yml')
with open(_config_file) as file_desc:
    _app_config: dict[str, any] = yaml.load(
        file_desc, Loader=yaml.SafeLoader
    )

_routers: list = [StatusRouter]
_app_type: AppType = AppType(_app_config['appserver']['app_type'])
if _app_type == AppType.CDN:
    _routers.append(CdnRouter)
elif _app_type == AppType.MODERATE:
    _routers.append(ModerateRouter)
else:
    raise ValueError(f'Unknown app type {_app_type}')

app = setup_api(
    'BYODA app server', 'A generic app server for a BYODA network',
    'v0.0.1', _routers,
    lifespan=lifespan, trace_server=config.trace_server,
)

config.app = app
