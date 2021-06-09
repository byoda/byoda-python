'''
POD server for Bring Your Own Data and Algorithms

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import sys

import uvicorn

import graphene

from starlette.graphql import GraphQLApp
from starlette.middleware import Middleware

from starlette_context import plugins
from starlette_context.middleware import RawContextMiddleware

from fastapi import FastAPI

from ariadne.asgi import GraphQL

from opentelemetry import trace
from opentelemetry.exporter import jaeger
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchExportSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from prometheus_fastapi_instrumentator import \
    Instrumentator as PrometheusInstrumentator

from byoda import config
from byoda.util.logger import Logger

# from byoda.datamodel import Server
from byoda.datamodel import Network

from byoda.datatypes import CloudType, IdType
from byoda.datastore import DocumentStoreType, DocumentStore

# from .bootstrap import LetsEncryptConfig
from .bootstrap import NginxConfig, NGINX_SITE_CONFIG_DIR

from byoda.datastore import MemberQuery

# from .routers import member

_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/pod.log'

network = {
    'cloud': CloudType(os.environ.get('CLOUD', 'AWS')),
    'bucket_prefix': os.environ['BUCKET_PREFIX'],
    'network': os.environ.get('NETWORK', 'byoda.net'),
    'account_id': os.environ.get('ACCOUNT_ID'),
    'account_secret': os.environ.get('ACCOUNT_SECRET'),
    'private_key_password': os.environ.get('PRIVATE_KEY_SECRET', 'byoda'),
    'loglevel': os.environ.get('LOGLEVEL', 'WARNING'),
    'root_dir': '/byoda',
    'roles': ['pod'],
}

debug = False
if network['loglevel'] == 'DEBUG':
    debug = True

_LOGGER = Logger.getLogger(
    sys.argv[0], json_out=False, debug=debug, loglevel=network['loglevel'],
    logfile=LOG_FILE
)

# TODO: Desired configuration for the LetsEncrypt TLS cert for the BYODA
# web interface
# tls_secret = TlsSecret(paths=paths, fqdn=account_secret.common_name)
# letsencrypt = LetsEncryptConfig(tls_secret)
# cert_status = letsencrypt.exists()
# if cert_status != CertStatus.OK:
#     letsencrypt.create()

config.network = Network(network, network)
config.document_store = DocumentStore.get_document_store(
    DocumentStoreType.OBJECT_STORE,
    cloud_type=CloudType.AWS,
    bucket_prefix=network['bucket_prefix'],
    root_dir=config.network.root_dir
)

nginx_config = NginxConfig(
    directory=NGINX_SITE_CONFIG_DIR,
    filename='virtualserver.conf',
    identifier=network['account_id'],
    id_type=IdType.ACCOUNT,
    alias=config.network.paths.account,
    network=config.network.network,
    public_cloud_endpoint=config.network.paths.storage_driver.get_url(
        public=True
    ),
)

if not nginx_config.exists():
    nginx_config.create()
    nginx_config.reload()

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
if config.app_config:
    jaeger_exporter = jaeger.JaegerSpanExporter(
        service_name='podserver',
        agent_host_name=config.app_config['application'].get(
            'jaeger_host', '127.0.0.1'
        ),
        agent_port=6831,
    )

    trace.get_tracer_provider().add_span_processor(
        BatchExportSpanProcessor(jaeger_exporter)
    )

app = FastAPI(
    title='BYODA pod server',
    description='The pod server for a BYODA network',
    version='v0.0.1',
    middleware=middleware
)
FastAPIInstrumentor.instrument_app(app)
PrometheusInstrumentator().instrument(app).expose(app)

# add_route is inherited from starlette. Not sure if decorators
# can be used here
# https://fastapi.tiangolo.com/advanced/graphql/
app.add_route(
    '/api/v1/member/data',
    GraphQLApp(schema=graphene.Schema(query=MemberQuery))
)


@app.get('/api/v1/status')
async def status():
    return {'status': 'healthy'}

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)
