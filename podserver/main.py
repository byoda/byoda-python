'''
POD server for Bring Your Own Data and Algorithms

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
from byoda.util.logger import Logger

from byoda.datamodel import Network
from byoda.datamodel import PodServer

from byoda.datatypes import CloudType, IdType
from byoda.datastore import DocumentStoreType

# from .bootstrap import LetsEncryptConfig
from .bootstrap import NginxConfig, NGINX_SITE_CONFIG_DIR

# from .routers import member

_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/pod.log'

DIR_API_BASE_URL = 'https://dir.{network}/api'

config.server = PodServer()
server = config.server

network_data = {
    'cloud': CloudType(os.environ.get('CLOUD', 'LOCAL')),
    'bucket_prefix': os.environ['BUCKET_PREFIX'],
    'network': os.environ.get('NETWORK', config.DEFAULT_NETWORK),
    'account_id': os.environ.get('ACCOUNT_ID'),
    'account_secret': os.environ.get('ACCOUNT_SECRET'),
    'private_key_password': os.environ.get('PRIVATE_KEY_SECRET', 'byoda'),
    'loglevel': os.environ.get('LOGLEVEL', 'WARNING'),
    'root_dir': os.environ.get('ROOT_DIR', '/byoda'),
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
server.account = network.load_account(
    network_data['account_id'], load_tls_secret=True
)

server.load_secrets(password=network.private_key_password)

server.get_registered_services(network)
server.load_joined_services(network)

config.server = server

try:
    server.load_secrets(password=network_data['private_key_password'])
    _LOGGER.debug('Read account secrets')
except Exception:
    # TODO: try to see if there is a error with accessing storage
    # and only if storage is available but the secrets are not, then
    # create new secrets
    _LOGGER.info('Creating account secrets')
    server.account.paths.create_secrets_directory()
    server.account.paths.create_account_directory()
    server.account.create_secrets()


# Save private key to ephemeral storage so that we can use it for:
# - NGINX virtual server for account
# - requests module for outbound API calls
key_file = server.account.tls_secret.save_tmp_private_key()

# Register pod to directory server
api = (
    DIR_API_BASE_URL.format(network=network_data['network']) +
    '/v1/network/account'
)

cert = (server.account.tls_secret.cert_file, key_file)
resp = requests.get(api, cert=cert)
_LOGGER.debug(f'Registered account with directory server: {resp.status_code}')


# TODO, needs an API on the directory server
src_dir = '/podserver/byoda-python'
ca_file = (
    network.paths.network_directory() +
    f'/network-{network_data["network"]}-root-ca-cert.pem'
)
server.network.paths.storage_driver.copy(
    f'{src_dir}/networks/network-{network_data["network"]}-root-ca-cert.pem',
    ca_file
)

if server.cloud != CloudType.LOCAL:
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
    )

    nginx_config.create()
    nginx_config.reload()

for service in network.services.values():
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
    uvicorn.run(app, host='127.0.0.1', port=8000)
