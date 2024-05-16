'''
Helper function to set up the Fastapi API, shared by directory, services
and pod servers and the functional test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from logging import getLogger

from starlette.middleware import Middleware
from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware
from starlette.middleware.cors import CORSMiddleware

from fastapi import FastAPI

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.resources import SERVICE_NAME

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter \
    import OTLPSpanExporter

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.metrics import get_meter_provider
from opentelemetry.metrics import set_meter_provider
from opentelemetry.metrics import Meter

# Prometheus exporter docs are in <pipenv-dir>/lib/python-3.12/site-packages/opentelemetry/exporter/prometheus/__init__.py  # noqa: E501
from opentelemetry.exporter.prometheus import PrometheusMetricReader

from prometheus_client import start_http_server

from byoda.util.logger import Logger

from byoda import config

_LOGGER: Logger = getLogger(__name__)


def setup_api(title: str, description: str, version: str, routers: list,
              lifespan: callable, trace_server: str = '127.0.0.1',
              cors: list[str] = []) -> FastAPI:

    updated_cors_hosts: list[str] = review_cors_hosts(cors)

    middleware: list[Middleware] = [
        Middleware(
            CORSMiddleware, allow_origins=updated_cors_hosts,
            allow_credentials=True, allow_methods=['*'],
            allow_headers=['*'], expose_headers=['*'], max_age=86400
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

    resource: Resource = Resource.create(
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

    try:
        start_http_server(port=5000, addr="localhost")
    except OSError:
        pass

    reader = PrometheusMetricReader('byopay')
    set_meter_provider(MeterProvider(metric_readers=[reader]))

    meter: Meter = get_meter_provider().get_meter('byopay', '0.0.1')
    config.meter = meter

    for router in routers:
        app.include_router(router.router)

    return app


def review_cors_hosts(hosts: str | list[str]) -> list[str]:
    '''
    Make sure all CORS hosts start with http:// or https://

    :param hosts: list of hosts to review
    :return: list of hosts with http:// or https:// prepended
    '''

    if isinstance(hosts, str):
        hosts = [hosts]
    elif isinstance(hosts, set):
        hosts = list(hosts)

    updated_cors_hosts: list[str] = []
    for host in hosts or []:
        if host == '*':
            return ['*']

        if not host.startswith('https://') and not host.startswith('http://'):
            updated_host: str = f'https://{host}'
            updated_cors_hosts.append(updated_host)
        else:
            updated_cors_hosts.append(host)

    if config.debug:
        updated_cors_hosts.append('http://localhost:3000')
        updated_cors_hosts.append('http://127.0.0.1:3000')

    return updated_cors_hosts


def update_cors_origins(hosts: str | list[str]) -> None:
    '''
    Updates the starlette CORS middleware to add the provided hosts

    :param hosts: list of hosts to add
    '''

    if not hosts:
        _LOGGER.debug('No CORS hosts to add')
        return

    app: FastAPI = config.app

    if config.test_case and not hasattr(app, 'user_middleware'):
        _LOGGER.debug('NOT updating CORS hosts')
        return

    updated_cors_hosts: list[str] = review_cors_hosts(hosts)
    for middleware in app.user_middleware or []:
        if middleware.cls == CORSMiddleware:
            if not hasattr(middleware, 'options'):
                raise KeyError('CORS middleware has no options attribute')

            for host in updated_cors_hosts:
                origins: str | None = middleware.options.get('allow_origins')
                if host not in origins or []:
                    _LOGGER.debug(f'Adding CORS host: {host}')
                    # app.user_middleware is a reference to
                    # app.middleware_stack.app (or vice versa)
                    middleware.options['allow_origins'].append(host)
            return

    raise KeyError('CORS middleware not found')
