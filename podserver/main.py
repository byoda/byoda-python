'''
POD server for Bring Your Own Data and Algorithms

The podserver relies on podserver/bootstrap.py to set up
the account, its secrets, restoring the database files
from the cloud storage, registering the pod and creating
the nginx configuration files for the account and for
existing memberships.

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
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys

from byoda import config
from byoda.util.logger import Logger

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.servers.pod_server import PodServer

from byoda.datatypes import CloudType
from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.util.fastapi import setup_api, add_cors

from .util import get_environment_vars

from .routers import account as AccountRouter
from .routers import member as MemberRouter
from .routers import authtoken as AuthTokenRouter
from .routers import status as StatusRouter
from .routers import accountdata as AccountDataRouter

_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/pod.log'

DIR_API_BASE_URL = 'https://dir.{network}/api'

# TODO: re-intro CORS origin ACL:
# account.tls_secret.common_name
app = setup_api(
    'BYODA pod server', 'The pod server for a BYODA network',
    'v0.0.1', [], [
        AccountRouter, MemberRouter, AuthTokenRouter, StatusRouter,
        AccountDataRouter
    ]
)


@app.on_event('startup')
async def setup():
    network_data = get_environment_vars()

    server: PodServer = PodServer(
        bootstrapping=bool(network_data.get('bootstrap'))
    )

    config.server = server

    # Remaining environment variables used:
    server.custom_domain = network_data['custom_domain']
    server.shared_webserver = network_data['shared_webserver']

    if str(network_data['debug']).lower() in ('true', 'debug', '1'):
        config.debug = True
        # Make our files readable by everyone, so we can
        # use tools like call_graphql.py to debug the server
        os.umask(0o0000)
    else:
        os.umask(0x0077)

    global _LOGGER
    _LOGGER = Logger.getLogger(
        sys.argv[0], json_out=False, debug=config.debug,
        loglevel=network_data['loglevel'], logfile=LOG_FILE
    )

    await server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType(network_data['cloud']),
        bucket_prefix=network_data['bucket_prefix'],
        root_dir=network_data['root_dir']
    )

    network = Network(network_data, network_data)
    await network.load_network_secrets()

    server.network = network
    server.paths = network.paths

    account = Account(network_data['account_id'], network)
    account.password = network_data.get('account_secret')

    await account.load_secrets()

    server.account = account

    await server.set_data_store(
        DataStoreType.SQLITE, account.data_secret
    )

    await server.get_registered_services()

    cors_origins = [
        f'https://proxy.{network.name}',
        f'https://{account.tls_secret.common_name}'
    ]

    if server.custom_domain:
        cors_origins.append(f'https://{server.custom_domain}')

    await account.load_memberships()

    for account_member in account.memberships.values():
        await account_member.create_query_cache()
        account_member.enable_graphql_api(app)
        cors_origins.append(f'https://{account_member.tls_secret.common_name}')

    _LOGGER.debug('Going to add CORS Origins')
    add_cors(app, cors_origins)
