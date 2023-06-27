'''
Copy of POD server with minor tweaks to run during tests

This file should remain in sync with podserver/main.py
except where noted in comments in the code

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys

###
### Test change     # noqa: E266
###
import shutil
from tests.lib.util import get_test_uuid
###
###
###

from byoda import config
from byoda.util.logger import Logger

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.servers.pod_server import PodServer

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.storage.pubsub_nng import PubSubNng

from byoda.util.fastapi import setup_api, add_cors

###
### Test change     # noqa: E266
###
from tests.lib.setup import mock_environment_vars
from tests.lib.setup import write_account_id
###
###
###

from podserver.util import get_environment_vars

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import status as StatusRouter
from podserver.routers import accountdata as AccountDataRouter
from podserver.routers import content_token as ContentTokenRouter

_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/pod.log'

DIR_API_BASE_URL = 'https://dir.{network}/api'

###
### Test change     # noqa: E266
###
TEST_DIR = '/tmp/byoda-tests/podserver'
###
###
###

# TODO: re-intro CORS origin ACL:
# account.tls_secret.common_name
app = setup_api(
    'BYODA pod server', 'The pod server for a BYODA network',
    'v0.0.1', [], [
        AccountRouter, MemberRouter, AuthTokenRouter, StatusRouter,
        AccountDataRouter, ContentTokenRouter
    ]
)


@app.on_event('startup')
async def setup():
    # HACK: Deletes files from tmp directory. Possible race condition
    # with other process so we do it right at the start
    PubSubNng.cleanup()

    ###
    ### Test change     # noqa: E266
    ###
    mock_environment_vars(TEST_DIR)
    ###
    ###
    ###

    data = get_environment_vars()

    ###
    ### Test change     # noqa: E266
    ###
    config.test_case = "TEST_SERVER"

    if data['root_dir']:
        try:
            shutil.rmtree(data['root_dir'])
        except FileNotFoundError:
            pass

        os.makedirs(data['root_dir'])
    else:
        data['root_dir'] = TEST_DIR
    ###
    ###
    ###

    server: PodServer = PodServer(
        bootstrapping=bool(data.get('bootstrap'))
    )

    config.server = server

    # Remaining environment variables used:
    server.custom_domain = data['custom_domain']
    server.shared_webserver = data['shared_webserver']

    if str(data['debug']).lower() in ('true', 'debug', '1'):
        config.debug = True
        # Make our files readable by everyone, so we can
        # use tools like call_graphql.py to debug the server
        os.umask(0o0000)
    else:
        os.umask(0x0077)

    ###
    ### Test change     # noqa: E266
    ###
    global LOG_FILE
    LOG_FILE = data['root_dir'] + '/pod.log'
    ###
    ###
    ###

    global _LOGGER
    _LOGGER = Logger.getLogger(
        sys.argv[0], json_out=False, debug=config.debug,
        loglevel=data['loglevel'], logfile=LOG_FILE
    )

    await server.set_document_store(
        DocumentStoreType.OBJECT_STORE, server.cloud,
        private_bucket=data['private_bucket'],
        restricted_bucket=data['restricted_bucket'],
        public_bucket=data['public_bucket'],
        root_dir=data['root_dir']
    )

    network = Network(data, data)
    await network.load_network_secrets()

    server.network = network
    server.paths = network.paths

    ###
    ### Test change     # noqa: E266
    ###
    data['account_id'] = get_test_uuid()
    write_account_id(data)
    ###
    ###
    ###

    account = Account(data['account_id'], network)
    account.password = data.get('account_secret')

    ###
    ### Test change     # noqa: E266
    ###
    await account.paths.create_account_directory()
    await account.create_account_secret()
    await account.tls_secret.save(
        account.private_key_password, overwrite=True,
        storage_driver=server.local_storage
    )
    account.tls_secret.save_tmp_private_key()
    await account.create_data_secret()
    account.data_secret.create_shared_key()
    await account.save_protected_shared_key()
    await account.register()
    ###
    ###
    ###
    # await account.load_secrets()

    server.account = account

    await server.set_data_store(
        DataStoreType.SQLITE, account.data_secret
    )

    await server.get_registered_services()

    ###
    ### Test change     # noqa: E266
    ###
    services = list(server.network.service_summaries.values())
    service = [
        service
        for service in services
        if service['name'] == 'byoda-tube'
    ][0]

    local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
    if local_service_contract:
        dest = TEST_DIR + '/' + local_service_contract
        dest_dir = os.path.dirname(dest)
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copyfile(
            local_service_contract, TEST_DIR + '/' + local_service_contract
        )

    member_id = get_test_uuid()
    await account.join(
        service['service_id'], service['version'], server.local_storage,
        member_id=member_id, local_service_contract=local_service_contract
    )
    ###
    ###
    ###
    # await server.get_registered_services()

    cors_origins = [
        f'https://proxy.{network.name}',
        f'https://{account.tls_secret.common_name}'
    ]

    if server.custom_domain:
        cors_origins.append(f'https://{server.custom_domain}')

    await account.load_memberships()

    for account_member in account.memberships.values():
        await account_member.create_query_cache()
        await account_member.create_counter_cache()
        account_member.enable_graphql_api(app)
        cors_origins.append(f'https://{account_member.tls_secret.common_name}')

    _LOGGER.debug('Going to add CORS Origins')
    add_cors(app, cors_origins, allow_proxy=True, debug=True)
