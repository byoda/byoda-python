'''
Set up the Fastapi API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from starlette.middleware import Middleware
from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware

from fastapi import FastAPI

from opentelemetry import trace
from opentelemetry.exporter import jaeger
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchExportSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from prometheus_fastapi_instrumentator import \
    Instrumentator as PrometheusInstrumentator

from .routers import account
from .routers import service

_LOGGER = logging.getLogger(__name__)


def setup_api(title, description, version, app_config):
    middleware = [
        Middleware(
            RawContextMiddleware,
            plugins=(
                plugins.RequestIdPlugin(),
                plugins.CorrelationIdPlugin()
            )
        )
    ]

    trace.set_tracer_provider(TracerProvider())
    if app_config:
        jaeger_exporter = jaeger.JaegerSpanExporter(
            service_name='dirserver',
            agent_host_name=app_config['application'].get(
                'jaeger_host', '127.0.0.1'
            ),
            agent_port=6831,
        )
        trace.get_tracer_provider().add_span_processor(
            BatchExportSpanProcessor(jaeger_exporter)
        )

    app = FastAPI(
        title=title, description=description, version=version,
        middleware=middleware
    )

    FastAPIInstrumentor.instrument_app(app)
    PrometheusInstrumentator().instrument(app).expose(app)

    app.include_router(account.router)
    app.include_router(service.router)

    return app
