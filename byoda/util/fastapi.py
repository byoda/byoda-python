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

from byoda import config

_LOGGER = logging.getLogger(__name__)


def setup_api(title: str, description: str, version: str, routers: list,
              lifespan: callable) -> FastAPI:
    middleware = [
        Middleware(
            CORSMiddleware, allow_origins=[], allow_credentials=True,
            allow_methods=['*'], allow_headers=['*'], expose_headers=['*'],
            max_age=86400
        ),
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

    # FastAPIInstrumentor.instrument_app(app)
    # PrometheusInstrumentator().instrument(app).expose(app)

    for router in routers:
        app.include_router(router.router)

    return app


def update_cors_origins(hosts: str | list[str]):
    '''
    Updates the starlette CORS middleware to add the provided hosts

    :param hosts: list of hosts to add
    '''

    if not hosts:
        _LOGGER.debug('No CORS hosts to add')
        return

    if isinstance(hosts, str):
        hosts = [hosts]

    app: FastAPI = config.app
    for middleware in app.user_middleware:
        if middleware.cls == CORSMiddleware:
            for host in hosts:
                if not host.startswith('https://'):
                    host = f'https://{host}'
                    
                if host not in middleware.options['allow_origins']:
                    _LOGGER.debug(f'Adding CORS host: {host}')
                    # app.user_middleware is a reference to
                    # app.middleware_stack.app (or vice versa)
                    middleware.options['allow_origins'].append(host)
            return

    raise KeyError('CORS middleware not found')
