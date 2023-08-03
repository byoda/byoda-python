#!/usr/bin/env python3

'''
Test the POD REST and GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import asyncio
import unittest
import requests

from uuid import UUID
from datetime import datetime, timezone

from gql import Client, gql
from gql.transport.websockets import WebsocketsTransport


from byoda.datamodel.account import Account
from byoda.datamodel.network import Network

from byoda.datastore.data_store import DataStoreType

from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.util.api_client.graphql_client import GraphQlClient

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import get_account_id

from tests.lib.defines import BASE_URL
from tests.lib.defines import BASE_WS_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.util import get_test_uuid
from tests.lib.util import get_account_tls_headers
from tests.lib.util import get_member_tls_headers

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/podserver'

POD_ACCOUNT: Account = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)

        config.test_case = 'TEST_CLIENT'

        network: Network = config.server.network
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        global BASE_WS_URL
        BASE_WS_URL = BASE_WS_URL.format(PORT=server.HTTP_PORT)

        network_data['account_id'] = get_account_id(network_data)

        account = Account(network_data['account_id'], network)
        account.password = network_data.get('account_secret')
        await account.load_secrets()

        server.account = account

        await config.server.set_data_store(
            DataStoreType.SQLITE, account.data_secret
        )

        await server.get_registered_services()

        app = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [account.tls_secret.common_name], [
                AccountRouter, MemberRouter, AuthTokenRouter,
                AccountDataRouter
            ],
            lifespan=None
        )

        for account_member in account.memberships.values():
            account_member.enable_graphql_api(app)

    @classmethod
    async def asyncTearDown(self):
        await GraphQlClient.close_all()

    async def test_graphql_websocket_append_no_filter(self):
        pod_account = config.server.account
        account_id = pod_account.account_id
        network = pod_account.network

        account_headers = get_account_tls_headers(account_id, network.name)

        API = BASE_URL + '/v1/pod/member'
        response = requests.get(
            API + f'/service_id/{ADDRESSBOOK_SERVICE_ID}', timeout=120,
            headers=account_headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        member_id = UUID(data['member_id'])
        member_headers = get_member_tls_headers(
            member_id, NETWORK, ADDRESSBOOK_SERVICE_ID
        )

        ws_url = f'{BASE_WS_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

        transport = WebsocketsTransport(
            url=ws_url,
            subprotocols=[WebsocketsTransport.GRAPHQLWS_SUBPROTOCOL],
            headers=member_headers
        )

        client = Client(transport=transport, fetch_schema_from_transport=False)
        session = await client.connect_async(reconnecting=True)

        request = GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['updates']
        message_updates = gql(request)

        # Test 1: no filter
        task_updates = asyncio.create_task(session.execute(message_updates,))
        task_append = asyncio.create_task(perform_append(member_id, 'follow'))

        subscribe_result, append_result = await asyncio.gather(
            task_updates, task_append
        )

        # Confirm the GraphQL append API call was successful.
        self.assertIsNone(append_result.get('errors'))
        append_data = append_result.get('data')
        self.assertIsNotNone(append_data)
        self.assertEqual(append_data['append_network_links'], 1)

        self.assertIsNone(subscribe_result.get('errors'))
        subscribe_data = subscribe_result.get('network_links_updates')
        self.assertEqual(
            subscribe_data['action'], 'append'
        )
        self.assertEqual(
            subscribe_data['data']['relation'], 'follow'
        )

        await client.close_async()

    async def test_graphql_counters(self):
        pod_account = config.server.account
        account_id = pod_account.account_id
        network = pod_account.network

        account_headers = get_account_tls_headers(account_id, network.name)

        API = BASE_URL + '/v1/pod/member'
        response = requests.get(
            API + f'/service_id/{ADDRESSBOOK_SERVICE_ID}', timeout=120,
            headers=account_headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        member_id = UUID(data['member_id'])
        member_headers = get_member_tls_headers(
            member_id, NETWORK, ADDRESSBOOK_SERVICE_ID
        )
        ws_url = f'{BASE_WS_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

        transport = WebsocketsTransport(
            url=ws_url,
            subprotocols=[WebsocketsTransport.GRAPHQLWS_SUBPROTOCOL],
            headers=member_headers, keep_alive_timeout=600
        )

        client = Client(transport=transport, fetch_schema_from_transport=False)
        session = await client.connect_async(reconnecting=True)

        message_counter = gql(
            GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['counter']
        )
        # Test 1: no filter
        task_counter = asyncio.create_task(
            session.execute(message_counter)
        )
        task_counter_filter_match = asyncio.create_task(
            session.execute(
                message_counter, {'filter': {'relation': 'follow'}}
            )
        )
        task_append = asyncio.create_task(perform_append(member_id, 'follow'))

        counter_result, counter_match_result, append_result = \
            await asyncio.gather(
                task_counter, task_counter_filter_match, task_append
            )

        # Confirm the GraphQL counter API call was successful.
        self.assertIsNone(counter_result.get('errors'))
        counter_data = counter_result.get('network_links_counter')
        self.assertEqual(counter_data['data'], 1)

        # Confirm the GraphQL counter API call with matching filter was
        # successful.
        self.assertIsNone(counter_match_result.get('errors'))
        counter_data = counter_match_result.get('network_links_counter')
        self.assertEqual(counter_data['data'], 1)

        # Confirm the GraphQL append API call was successful.
        self.assertIsNone(append_result.get('errors'))
        append_data = append_result.get('data')
        self.assertIsNotNone(append_data)
        self.assertEqual(append_data['append_network_links'], 1)

        # Now delete the item and confirm the counter is decremented
        task_counter = asyncio.create_task(
            session.execute(message_counter)
        )
        task_delete = asyncio.create_task(perform_delete(member_id, 'follow'))

        counter_result, delete_result = await asyncio.gather(
            task_counter, task_delete
        )

        self.assertIsNone(counter_result.get('errors'))
        counter_data = counter_result.get('network_links_counter')
        self.assertEqual(counter_data['data'], 0)

        # Confirm the GraphQL append API call was successful.
        self.assertIsNone(delete_result.get('errors'))
        delete_data = delete_result.get('data')
        self.assertIsNotNone(delete_data)
        self.assertEqual(delete_data['delete_from_network_links'], 1)

        await client.close_async()

    async def test_graphql_websocket_append_with_matching_filter(self):
        pod_account = config.server.account
        account_id = pod_account.account_id
        network = pod_account.network

        account_headers = get_account_tls_headers(account_id, network.name)

        API = BASE_URL + '/v1/pod/member'
        response = requests.get(
            API + f'/service_id/{ADDRESSBOOK_SERVICE_ID}', timeout=120,
            headers=account_headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        member_id = UUID(data['member_id'])
        member_headers = get_member_tls_headers(
            member_id, NETWORK, ADDRESSBOOK_SERVICE_ID
        )

        ws_url = f'{BASE_WS_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

        transport = WebsocketsTransport(
            url=ws_url,
            subprotocols=[WebsocketsTransport.GRAPHQLWS_SUBPROTOCOL],
            headers=member_headers

        )

        client = Client(transport=transport, fetch_schema_from_transport=False)
        session = await client.connect_async(reconnecting=True)

        request = GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['updates']
        message = gql(request)

        # Test 2: filter for matching relation
        vars = {
            'filters': {'relation': {'eq': 'friend'}}
        }
        task1 = asyncio.create_task(session.execute(message, vars))
        task2 = asyncio.create_task(perform_append(member_id, 'friend'))

        subscribe_result, append_result = await asyncio.gather(task1, task2)

        # Confirm the GraphQL append API call was successful.
        self.assertIsNone(append_result.get('errors'))
        append_data = append_result.get('data')
        self.assertIsNotNone(append_data)
        self.assertEqual(append_data['append_network_links'], 1)

        # Confirm our update subscription has received the result
        self.assertIsNone(subscribe_result.get('errors'))
        subscribe_data = subscribe_result.get('network_links_updates')
        self.assertEqual(
            subscribe_data['action'], 'append'
        )
        self.assertEqual(
            subscribe_data['data']['relation'], 'friend'
        )

        await client.close_async()

    async def test_graphql_websocket_append_with_not_matching_filter(self):
        pod_account = config.server.account
        account_id = pod_account.account_id
        network = pod_account.network

        account_headers = get_account_tls_headers(account_id, network.name)

        API = BASE_URL + '/v1/pod/member'
        response = requests.get(
            API + f'/service_id/{ADDRESSBOOK_SERVICE_ID}', timeout=120,
            headers=account_headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        member_id = UUID(data['member_id'])
        member_headers = get_member_tls_headers(
            member_id, NETWORK, ADDRESSBOOK_SERVICE_ID
        )
        ws_url = f'{BASE_WS_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

        transport = WebsocketsTransport(
            url=ws_url,
            subprotocols=[WebsocketsTransport.GRAPHQLWS_SUBPROTOCOL],
            headers=member_headers,
            keep_alive_timeout=600, pong_timeout=600

        )

        client = Client(transport=transport, fetch_schema_from_transport=False)
        session = await client.connect_async(reconnecting=True)

        request = GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['updates']
        message = gql(request)

        # Test 3: filter with no matching relation
        vars = {
            'filters': {'relation': {'eq': 'blah'}}
        }
        task1 = asyncio.create_task(session.execute(message, vars))
        # First we add a network_link with a relation that does not match
        task2 = asyncio.create_task(perform_append(member_id, 'friend'))
        # Now we add a network_link with a relation that does match
        task3 = asyncio.create_task(perform_append(member_id, 'blah'))

        subscribe_result, append_friend_result, append_blah_result = \
            await asyncio.gather(task1, task2, task3)

        # Confirm the two GraphQL append API calls weres successful.
        self.assertIsNone(append_friend_result.get('errors'))
        append_data = append_friend_result.get('data')
        self.assertIsNotNone(append_data)
        self.assertEqual(append_data['append_network_links'], 1)

        self.assertIsNone(append_blah_result.get('errors'))
        append_data = append_blah_result.get('data')
        self.assertIsNotNone(append_data)
        self.assertEqual(append_data['append_network_links'], 1)

        # Confirm our update subscription has received the result of the
        # second append
        self.assertIsNone(subscribe_result.get('errors'))
        subscribe_data = subscribe_result.get('network_links_updates')
        self.assertEqual(
            subscribe_data['action'], 'append'
        )
        self.assertEqual(
            subscribe_data['data']['relation'], 'blah'
        )

        await client.close_async()


async def perform_append(member_id: UUID, relation: str) -> object:
    await asyncio.sleep(1)
    url = f'{BASE_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

    member_headers = get_member_tls_headers(
        member_id, NETWORK, ADDRESSBOOK_SERVICE_ID
    )

    vars = {
        'member_id': str(get_test_uuid()),
        'relation': relation,
        'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())
    }

    response = await GraphQlClient.call(
        url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['append'], vars=vars,
        timeout=120, headers=member_headers
    )
    result = await response.json()

    return result


async def perform_delete(member_id: UUID, relation: str) -> object:
    await asyncio.sleep(1)
    url = f'{BASE_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

    member_headers = get_member_tls_headers(
        member_id, NETWORK, ADDRESSBOOK_SERVICE_ID
    )

    vars = {
        'filters': {'relation': {'eq': relation}},
    }

    response = await GraphQlClient.call(
        url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['delete'], vars=vars,
        timeout=120, headers=member_headers
    )
    result = await response.json()

    return result


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
