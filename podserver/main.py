'''
POD server for Bring Your Own Data and Algorithms

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import sys
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

from byoda import config
from byoda.util import Paths
from byoda.util.logger import Logger
from byoda.util.secrets import AccountSecret, TlsSecret

# from byoda.datamodel import Server
from byoda.datamodel import Network

from byoda.datatypes import CloudType, CertStatus

from byoda.storage.filestorage import FileStorage

from .bootstrap import AccountConfig
# from .bootstrap import LetsEncryptConfig

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
    sys.argv[0], debug=Ddebug, loglevel=network['loglevel'], logfile=LOG_FILE
)

private_object_storage = FileStorage.get_storage(
    network['cloud'], network['bucket_prefix'] + '_private',
    network['root_dir']
)

# Paths class defines where all the BYODA certs/keys are stored
paths = Paths(
    root_directory=network['root_dir'], network_name=network['network'],
    account_alias='pod', storage_driver=private_object_storage
)

paths.create_secrets_directory()
paths.create_account_directory()

# Desired configuration for the BYODA account
account = AccountConfig(
    network['cloud'], network['bucket_prefix'], network['network'],
    network['account_id'], network['account_secret'],
    network['private_key_password'], paths
)

if not account.exists():
    account.create()

account_secret = AccountSecret(paths)
account_secret.load(password=network['private_key_password'])

# TODO: Desired configuration for the LetsEncrypt TLS cert for the BYODA
# web interface
# tls_secret = TlsSecret(paths=paths, fqdn=account_secret.common_name)
# letsencrypt = LetsEncryptConfig(tls_secret)
# cert_status = letsencrypt.exists()
# if cert_status != CertStatus.OK:
#     letsencrypt.create()

config.network = Network(network, network)

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


@app.get('/api/v1/status')
async def status():
    return {'status': 'healthy'}

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)
