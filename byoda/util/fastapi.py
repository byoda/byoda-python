'''
Helper function to set up the Fastapi API, shared by directory, services
and pod servers and the functional test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from logging import getLogger
from byoda.util.logger import Logger

from starlette.middleware import Middleware
from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware
from starlette.middleware.cors import CORSMiddleware

from fastapi import FastAPI

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter \
    import OTLPSpanExporter

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from byoda import config

_LOGGER: Logger = getLogger(__name__)


def setup_api(title: str, description: str, version: str, routers: list,
              lifespan: callable, trace_server: str = '127.0.0.1') -> FastAPI:
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

    config.app = app

    resource = Resource.create(
        attributes={SERVICE_NAME: title.replace(' ', '-')}
    )
    provider = TracerProvider(resource=resource)

    otlp_exporter = OTLPSpanExporter(
        endpoint=f'http://{trace_server}:4317', insecure=True
    )

    processor = BatchSpanProcessor(
        otlp_exporter, max_export_batch_size=2
    )
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    config.tracer = trace.get_tracer(__name__)

    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls='/api/v1/status'
    )
    SQLite3Instrumentor().instrument()
    HTTPXClientInstrumentor().instrument()

    if config.debug:
        from prometheus_client import make_asgi_app
        from prometheus_client import CollectorRegistry
        from prometheus_client import multiprocess

        def make_metrics_app():
            registry = CollectorRegistry()
            os.environ['prometheus_multiproc_dir'] = '/tmp'
            multiprocess.MultiProcessCollector(registry)
            return make_asgi_app(registry=registry)

        metrics_app = make_metrics_app()
        app.mount("/metrics", metrics_app)

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
    elif isinstance(hosts, set):
        hosts = list(hosts)

    if config.debug:
        hosts.append('http://localhost:3000')

    app: FastAPI = config.app

    if config.test_case and not hasattr(app, 'user_middleware'):
        _LOGGER.debug('NOT updating CORS hosts')
        return

    for middleware in app.user_middleware or []:
        if middleware.cls == CORSMiddleware:
            for host in hosts:
                if (not host.startswith('https://') and
                        not host.startswith('http://') and host != '*'):
                    host = f'https://{host}'

                if host not in middleware.options['allow_origins']:
                    _LOGGER.debug(f'Adding CORS host: {host}')
                    # app.user_middleware is a reference to
                    # app.middleware_stack.app (or vice versa)
                    middleware.options['allow_origins'].append(host)
            return

    raise KeyError('CORS middleware not found')
