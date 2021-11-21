'''
POD server for Bring Your Own Data and Algorithms

Suported environment variables:
CLOUD: 'AWS', 'LOCAL'
BUCKET_PREFIX
NETWORK
ACCOUNT_ID
ACCOUNT_SECRET
PRIVATE_KEY_SECRET: secret to protect the private key
LOGLEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL
ROOT_DIR: where files need to be cached (if object storage is used) or stored

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import os
import sys

import requests

import uvicorn
from starlette.graphql import GraphQLApp

from .api import setup_api

from byoda import config
from byoda.util import Paths
from byoda.util.logger import Logger

from byoda.datamodel import Network
from byoda.datamodel import Account
from byoda.datamodel.service import BYODA_PRIVATE_SERVICE

from byoda.servers import PodServer

from byoda.datatypes import CloudType, IdType
from byoda.datastore import DocumentStoreType

# from .bootstrap import LetsEncryptConfig
from byoda.util import NginxConfig, NGINX_SITE_CONFIG_DIR

# from .routers import member

_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/pod.log'

DIR_API_BASE_URL = 'https://dir.{network}/api'

config.server = PodServer()
server = config.server


# When we are bootstrapping, we create any secrets that are missing.
# The BOOTSTRAP environment variable should only be set during
# initial creation of the pod as otherwise existing secrets might
# be discarded when there issues with accessing the storage bucket
bootstrap = os.environ.get('BOOTSTRAP', None)

# Remaining environment variables used:
network_data = {
    'cloud': CloudType(os.environ.get('CLOUD', 'LOCAL')),
    'bucket_prefix': os.environ['BUCKET_PREFIX'],
    'network': os.environ.get('NETWORK', config.DEFAULT_NETWORK),
    'account_id': os.environ.get('ACCOUNT_ID'),
    'account_secret': os.environ.get('ACCOUNT_SECRET'),
    'private_key_password': os.environ.get('PRIVATE_KEY_SECRET', 'byoda'),
    'loglevel': os.environ.get('LOGLEVEL', 'WARNING'),
    'root_dir': os.environ.get('ROOT_DIR', '/byoda-pod'),
    'roles': ['pod'],
}

debug = False
if network_data['loglevel'] == 'DEBUG':
    debug = True

_LOGGER = Logger.getLogger(
    sys.argv[0], json_out=False, debug=debug,
    loglevel=network_data['loglevel'], logfile=LOG_FILE
)

server.set_document_store(
    DocumentStoreType.OBJECT_STORE,
    cloud_type=CloudType(network_data['cloud']),
    bucket_prefix=network_data['bucket_prefix'],
    root_dir=network_data['root_dir']
)

# TODO: Desired configuration for the LetsEncrypt TLS cert for the BYODA
# web interface
# tls_secret = TlsSecret(paths=paths, fqdn=account_secret.common_name)
# letsencrypt = LetsEncryptConfig(tls_secret)
# cert_status = letsencrypt.exists()
# if cert_status != CertStatus.OK:
#     letsencrypt.create()

network = Network(network_data, network_data)

server.network = network
server.paths = network.paths

server.get_registered_services()

# TODO: if we have a pod secret, should we compare its commonname with the
# account_id environment variable?
account = Account(network_data['account_id'], network, bootstrap=bootstrap)

server.account = account

try:
    account.tls_secret.load(
        password=account.private_key_password
    )
    _LOGGER.debug('Read account TLS secret')
except FileNotFoundError:
    if bootstrap:
        account.create_account_secret()
        _LOGGER.info('Creating account secret during bootstrap')
    else:
        raise ValueError('Failed to load account TLS secret')

try:
    account.data_secret.load(
        password=account.private_key_password
    )
    _LOGGER.debug('Read account data secret')
except FileNotFoundError:
    if bootstrap:
        account.create_data_secret()
        _LOGGER.info('Creating account secret during bootstrap')
    else:
        raise ValueError('Failed to load account TLS secret')


config.server = server

server.account.register()

nginx_config = NginxConfig(
    directory=NGINX_SITE_CONFIG_DIR,
    filename='virtualserver.conf',
    identifier=network_data['account_id'],
    subdomain=IdType.ACCOUNT.value,
    cert_filepath='',
    key_filepath='',
    alias=network.paths.account,
    network=network.name,
    public_cloud_endpoint=network.paths.storage_driver.get_url(
        public=True
    ),
    port=PodServer.HTTP_PORT,
    root_dir=server.network.paths.root_directory
)

nginx_config.create()
nginx_config.reload()

if bootstrap and BYODA_PRIVATE_SERVICE not in network.services:
    server.join_service(BYODA_PRIVATE_SERVICE, network_data)

for service in network.services.values():
    service.load_schema(service.paths.get(Paths.SERVICE_FILE))
    service.schema.generate_graphql_schema()

app = setup_api(
    'BYODA pod server', 'The pod server for a BYODA network',
    'v0.0.1', config.app_config
)

for service in network.services.values():
    app.add_route(
        f'/api/v1/data/service-{service.service_id}',
        GraphQLApp(schema=service.schema.gql_schema)
    )


@app.get('/api/v1/status')
async def status():
    return {'status': 'healthy'}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=PodServer.HTTP_PORT)
