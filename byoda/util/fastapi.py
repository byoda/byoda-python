'''
Helper function to set up the Fastapi API, shared by directory, services
and pod servers and the functional test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from starlette.middleware import Middleware
from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware
from starlette.middleware.cors import CORSMiddleware

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from byoda.datamodel.network import Network

from byoda import config

_LOGGER = logging.getLogger(__name__)


def setup_api(title: str, description: str, version: str,
              cors_origins: list[str], routers: list, lifespan: callable
              ) -> FastAPI:
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
        middleware=middleware, debug=True, lifespan=lifespan
    )

    # TODO: reenable CORS
    # if cors_origins:
    #    add_cors(app, cors_origins)

    # FastAPIInstrumentor.instrument_app(app)
    # PrometheusInstrumentator().instrument(app).expose(app)

    for router in routers:
        app.include_router(router.router)

    return app


def add_cors(app: FastAPI, cors_origins: list[str], allow_proxy: bool = True,
             debug: bool = False):
    '''
    Add CORS headers to the app
    '''

    network: Network = config.server.network

    if debug:
        cors_origins = ['*']
    else:
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
        expose_headers=['*'],
        max_age=86400,
    )
