'''
Helper function to set up the Fastapi API, shared by directory, services
and pod servers and the functional test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import List

from starlette.middleware import Middleware
from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from byoda.datamodel.network import Network

from byoda import config

_LOGGER = logging.getLogger(__name__)


def setup_api(title: str, description: str, version: str,
              cors_origins: List[str], routers: List):
    middleware = [
        Middleware(
            RawContextMiddleware,
            plugins=(
                plugins.RequestIdPlugin(),
                plugins.CorrelationIdPlugin()
            )
        )
    ]

    app = FastAPI(
        title=title, description=description, version=version,
        middleware=middleware
    )

    if cors_origins:
        add_cors(app, cors_origins)

    # FastAPIInstrumentor.instrument_app(app)
    # PrometheusInstrumentator().instrument(app).expose(app)

    for router in routers:
        app.include_router(router.router)

    return app


def add_cors(app: FastAPI, cors_origins: List[str], allow_proxy: bool = True):
    '''
    Add CORS headers to the app
    '''

    network: Network = config.server.network

    # SECURITY: remove this when in production
    test_url = 'https://byoda-pod-manger.web.app'
    cors_origins.append(test_url)

    proxy_url = f'https://proxy.{network.name}'
    if allow_proxy and proxy_url not in cors_origins:
        cors_origins.append(proxy_url)

    _LOGGER.debug(
        f'Adding CORS middleware for origins {", ".join(cors_origins)}'
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )
