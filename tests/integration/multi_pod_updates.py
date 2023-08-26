#!/usr/bin/env python3

'''
Test receiving websocket updates from multiple pods


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys

from uuid import UUID

import trio

from gql import Client, gql
from gql.transport.websockets import WebsocketsTransport

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datastore.data_store import DataStoreType

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger
from byoda import config

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account

from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import AWS_POD_MEMBER_ID
from tests.lib.defines import GCP_POD_MEMBER_ID
from tests.lib.defines import HOME_POD_MEMBER_ID
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

from tests.lib.util import get_member_tls_headers

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK
TIMEOUT: int = 900
TEST_DIR: str = '/tmp/byoda-tests/multi_pod_updates'

_LOGGER = None

POD_ACCOUNT: Account = None


async def main():
    mock_environment_vars(TEST_DIR)
    network_data = await setup_network(delete_tmp_dir=True)
    account = await setup_account(network_data)

    server: PodServer = config.server

    server.account: Account = account

    await server.set_data_store(
        DataStoreType.SQLITE, account.data_secret
    )

    await server.get_registered_services()

    pod_account: Account = config.server.account
    service_id = ADDRESSBOOK_SERVICE_ID
    member: Member = await pod_account.get_membership(service_id)
    auth_headers = get_member_tls_headers(
        member.member_id, member.network, service_id
    )

    targets = set(
        [
            AZURE_POD_MEMBER_ID, AWS_POD_MEMBER_ID, GCP_POD_MEMBER_ID,
            HOME_POD_MEMBER_ID
        ]
    )
    query = gql(GRAPHQL_STATEMENTS['channels']['update'])

    # async with trio.open_nursery() as nursery:
    #     pass
        # for remote_member in targets:
        #     nursery.start_soon(
        #         get_updates, remote_member, auth_headers, query
        #     )

    raise RuntimeError('I do not think we should ever get here')


async def get_updates(member_id: UUID, service_id: int, headers: dict[str:str],
                      query):
    ws_url = (
        f'ws://{member_id}.members-{service_id}'
        f'/api/v1/data/service-{service_id}'
    )

    transport = WebsocketsTransport(
        url=ws_url, subprotocols=[WebsocketsTransport.GRAPHQLWS_SUBPROTOCOL],
        headers=headers
    )

    client = Client(transport=transport, fetch_schema_from_transport=False)
    session = await client.connect_async(reconnecting=True)
    while True:
        result = await session.execute(query)
        print('Received update')
        data = result.get('data')
        print(f'Received: {data}')


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    trio.run(main)
    # asyncio.run(main())
