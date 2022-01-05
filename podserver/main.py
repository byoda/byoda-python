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
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import sys

import uvicorn

from byoda import config
from byoda.util import Logger

from byoda.datamodel import Network
from byoda.datamodel import Account

from byoda.servers import PodServer

from byoda.datatypes import CloudType, IdType, StorageType
from byoda.datastore import DocumentStoreType

from byoda.util import NginxConfig, NGINX_SITE_CONFIG_DIR

from byoda.util import setup_api

from .util import get_environment_vars

from .routers import account
from .routers import member

_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/pod.log'

DIR_API_BASE_URL = 'https://dir.{network}/api'

config.server = PodServer()
server = config.server

# Remaining environment variables used:
network_data = get_environment_vars()

_LOGGER = Logger.getLogger(
    sys.argv[0], json_out=False, debug=network_data['debug'],
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
pod_account = Account(network_data['account_id'], network, bootstrap=False)
pod_account.tls_secret.load(password=pod_account.private_key_password)
pod_account.data_secret.load(password=pod_account.private_key_password)
pod_account.register()

server.account = pod_account

nginx_config = NginxConfig(
    directory=NGINX_SITE_CONFIG_DIR,
    filename='virtualserver.conf',
    identifier=network_data['account_id'],
    subdomain=IdType.ACCOUNT.value,
    cert_filepath=(
        server.paths.root_directory() + '/' + pod_account.tls_secret.cert_file
    ),
    key_filepath=pod_account.tls_secret.unencrypted_private_key_file,
    alias=network.paths.account,
    network=network.name,
    public_cloud_endpoint=network.paths.storage_driver.get_url(
        StorageType.PUBLIC
    ),
    port=PodServer.HTTP_PORT,
    root_dir=server.network.paths.root_directory()
)

nginx_config.create()
nginx_config.reload()

app = setup_api(
    'BYODA pod server', 'The pod server for a BYODA network',
    'v0.0.1', None, [account, member]
)

for account_member in pod_account.memberships.values():
    account_member.enable_graphql_api(app)
    account_member.update_registration()


@app.get('/api/v1/status')
async def status():
    return {'status': 'healthy'}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=PodServer.HTTP_PORT)
