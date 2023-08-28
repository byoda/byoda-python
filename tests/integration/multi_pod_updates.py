#!/usr/bin/env python3

'''
Test receiving websocket updates from multiple pods


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import ssl
import shutil

from uuid import UUID


from anyio import run, sleep, create_task_group

from gql import Client, gql
from gql.transport.websockets import WebsocketsTransport

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.datastore.data_store import DataStoreType

from byoda.storage.filestorage import FileStorage

from byoda.storage.pubsub_nng import PubSubNng

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger
from byoda import config

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network

from tests.lib.defines import AZURE_POD_ACCOUNT_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import AWS_POD_MEMBER_ID
from tests.lib.defines import GCP_POD_MEMBER_ID
from tests.lib.defines import HOME_POD_MEMBER_ID
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK
TIMEOUT: int = 900
TEST_DIR: str = '/tmp/byoda-tests/multi_pod_updates'

_LOGGER = None


def copy_test_collateral_files(dest_dir: str = TEST_DIR):
    files = (
        'azure-pod-member-cert.pem', 'azure-pod-member.key',
        'azure-pod-member-data-cert.pem', 'azure-pod-member-data.key',
        'azure-pod-private-key-password'
    )
    local_collateral_dir = 'tests/collateral/local'
    for file in files:
        shutil.copy(f'{local_collateral_dir}/{file}', f'{dest_dir}/{file}')


async def azure_account_setup(dir_prefix: str = TEST_DIR):
    PubSubNng.cleanup()

    server: PodServer = config.server

    azure_account = Account(
        AZURE_POD_ACCOUNT_ID, network=server.network
    )
    azure_member = Member(
        ADDRESSBOOK_SERVICE_ID, azure_account
    )
    azure_member.member_id = AZURE_POD_MEMBER_ID

    tls_secret = MemberSecret(
        azure_member.member_id, azure_member.service_id, account=azure_account
    )

    tls_secret.cert_file = 'azure-pod-member-cert.pem'
    tls_secret.private_key_file = 'azure-pod-member.key'
    with open(f'{dir_prefix}/azure-pod-private-key-password') as file_desc:
        private_key_password = file_desc.read().strip()

    await tls_secret.load(
        with_private_key=True, password=private_key_password
    )

    data_secret = MemberDataSecret(
        azure_member.member_id, azure_member.service_id
    )

    data_secret.cert_file = 'azure-pod-member-data-cert.pem'
    data_secret.private_key_file = 'azure-pod-member-data.key'

    await data_secret.load(
        with_private_key=True, password=private_key_password
    )

    await config.server.set_data_store(
        DataStoreType.SQLITE, azure_account.data_secret
    )

    return (azure_account, tls_secret, data_secret, private_key_password)


async def main():
    mock_environment_vars(TEST_DIR)
    network_data = await setup_network(delete_tmp_dir=True)
    copy_test_collateral_files(TEST_DIR)
    network_data['account_id'] = AZURE_POD_ACCOUNT_ID

    account, tls_secret, data_secret, private_key_password = \
        await azure_account_setup()

    server: PodServer = config.server
    network: str = server.network.name
    await server.get_registered_services()

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ca_file: str = \
        f'{TEST_DIR}/network-{network}/network-{network}-root-ca-cert.pem'

    ssl_context.load_verify_locations(ca_file)
    ssl_context.load_cert_chain(
        certfile=f'{TEST_DIR}/{tls_secret.cert_file}',
        keyfile=f'{TEST_DIR}/{tls_secret.private_key_file}',
        password=private_key_password
    )

    targets = set(
        [
            AWS_POD_MEMBER_ID, GCP_POD_MEMBER_ID,
            HOME_POD_MEMBER_ID
        ]
    )
    service_id: int = ADDRESSBOOK_SERVICE_ID
    query = gql(GRAPHQL_STATEMENTS['channels']['update'])

    async with create_task_group() as tg:
        for remote_member in targets:
            tg.start_soon(
                get_updates, remote_member, service_id, network, ssl_context,
                query
            )

    raise RuntimeError('I do not think we should ever get here')


async def get_updates(member_id: UUID, service_id: int, network_name: str,
                      ssl_context: ssl.SSLContext, query):
    ws_url = (
        f'wss://{member_id}.members-{service_id}.{network_name}:444'
        f'/ws-api/v1/data/service-{service_id}'
    )

    transport = WebsocketsTransport(
        url=ws_url, subprotocols=[WebsocketsTransport.GRAPHQLWS_SUBPROTOCOL],
        ssl=ssl_context
    )

    client = Client(transport=transport, fetch_schema_from_transport=False)
    _LOGGER.debug(f'Connecting to remote member at {ws_url}')
    session = await client.connect_async(reconnecting=True)
    while True:
        result = await session.execute(query)
        print('Received update')
        data = result.get('data')
        print(f'Received: {data}')


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    run(main, backend='asyncio', backend_options={'use_uvloop': True})
