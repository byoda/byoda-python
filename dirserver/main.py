'''
API server for Bring Your Own Data and Algorithms

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import sys
import yaml
import uvicorn

from starlette.middleware import Middleware

from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware

from fastapi import FastAPI

from opentelemetry import trace
from opentelemetry.exporter import jaeger
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchExportSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from prometheus_fastapi_instrumentator import Instrumentator \
    as PrometheusInstrumentator

from .routers import account

from byoda.util.logger import Logger
from byoda import config

from byoda.datamodel import DirectoryServer
from byoda.datamodel import Network


_LOGGER = None

with open('config.yml') as file_desc:
    config.app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

debug = config.app_config['application']['debug']
verbose = not debug
_LOGGER = Logger.getLogger(
    sys.argv[0], debug=debug, verbose=verbose,
    logfile=config.app_config['application'].get('logfile')
)

server = DirectoryServer()
server.network = Network(
    config.app_config['dirserver'], config.app_config['application']
)
config.server = server
config.network = server.network

if not os.environ.get('SERVER_NAME') and config.network.name:
    os.environ['SERVER_NAME'] = config.network.name

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
jaeger_exporter = jaeger.JaegerSpanExporter(
    service_name='dirserver',
    agent_host_name=config.app_config['application'].get(
        'jaeger_host', '127.0.0.1'
    ),
    agent_port=6831,
)
trace.get_tracer_provider().add_span_processor(
    BatchExportSpanProcessor(jaeger_exporter)
)

app = FastAPI(
    title='BYODA directory server',
    description='The directory server for a BYODA network',
    version='v0.0.1',
    middleware=middleware
)
FastAPIInstrumentor.instrument_app(app)
PrometheusInstrumentator().instrument(app).expose(app)

app.include_router(account.router)


@app.get('/api/v1/status')
async def status():
    return {'status': 'healthy'}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
