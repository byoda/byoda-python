#!/usr/bin/env python3

'''
Test the POD REST and GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

These tests need a local webserver running on port 8000 as the
pynng does not allow you to spawn a server from the test code.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import sys
import asyncio
import unittest
import requests

from uuid import UUID
from datetime import datetime
from datetime import timezone

import websockets
from byoda.datamodel.network import Network
from byoda.datamodel.member import Member
from byoda.datamodel.account import Account

from byoda.datatypes import DataRequestType
from byoda.datatypes import MARKER_NETWORK_LINKS
from byoda.datatypes import DATA_API_URL

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpMethod
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import get_account_id

from tests.lib.defines import BASE_URL
from tests.lib.defines import BASE_WS_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.util import get_test_uuid
from tests.lib.util import get_account_tls_headers
from tests.lib.util import get_member_tls_headers


# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/podserver'

POD_ACCOUNT: Account = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)

        config.test_case = 'TEST_CLIENT'

        server: PodServer = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        network_data['account_id'] = get_account_id(network_data)

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

        config.trace_server: str = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        global APP
        APP = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [
                AccountRouter, MemberRouter, AuthTokenRouter,
                AccountDataRouter
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        for member in account.memberships.values():
            await member.create_query_cache()
            await member.create_counter_cache()
            await member.enable_data_apis(APP)

    @classmethod
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_graphql_websocket_append_no_filter(self):
        account: Account = config.server.account
        network: Network = account.network
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        member_id: UUID = member.member_id

        member_headers = get_member_tls_headers(
            member.member_id, network.name, service_id
        )

        class_name: str = MARKER_NETWORK_LINKS
        ws_data_url: str = DATA_API_WS_URL.format(
            protocol='ws', fqdn='127.0.0.1', port=8000, service_id=service_id,
            class_name=class_name, action=DataRequestType.UPDATES.value
        )

        webs = websockets.connect(
                ws_data_url, extra_headers=member_headers
            )
        await webs.send(ws_data_url))
        message = await webs.recv()
        request = {'query_id': str(get_test_uuid())}
        message_updates = gql(request)

        # Test 1: no filter
        task_updates = asyncio.create_task(session.execute(message_updates,))
        task_append = asyncio.create_task(perform_append(member_id, 'follow'))

        subscribe_result, append_result = await asyncio.gather(
            task_updates, task_append
        )

        # Confirm the REST API Append call was successful.
        self.assertTrue(bool(append_result))

        subscribe_data = subscribe_result.get('network_links_updates')
        self.assertEqual(
            subscribe_data['action'], 'append'
        )
        self.assertEqual(
            subscribe_data['data']['relation'], 'follow'
        )

        await client.close_async()

    async def test_graphql_counters(self):
        server: PodServer = config.server
        account: Account = server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        member_id: UUID = member.member_id
        network: Network = server.network

        member_headers = get_member_tls_headers(
            member_id, network.name, service_id
        )
        ws_url = DATA_API_WS_URL.format(

        )

        transport = WebsocketsTransport(
            url=ws_url,
            subprotocols=[WebsocketsTransport.GRAPHQLWS_SUBPROTOCOL],
            headers=member_headers, keep_alive_timeout=600
        )

        client = Client(transport=transport, fetch_schema_from_transport=False)
        session = await client.connect_async(reconnecting=True)

        message_counter = gql({'query_id': str(get_test_uuid())})

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

        # Confirm the REST Data counter API call was successful.
        self.assertTrue(counter_result)

        # Confirm the REST Data counter API call with matching filter was
        # successful.
        self.assertIsTrue(counter_match_result)

        # Confirm the REST Append API call was successful.
        self.assertTrue(append_result)

        # Now delete the item and confirm the counter is decremented
        task_counter = asyncio.create_task(session.execute(message_counter))

        task_delete = asyncio.create_task(perform_delete(member_id, 'follow'))

        counter_result, delete_result = await asyncio.gather(
            task_counter, task_delete
        )

        self.assertEqual(counter_result, 0)

        # Confirm the REST Append API call was successful.
        self.assertTrue(delete_result)

        await client.close_async()

    async def test_graphql_websocket_append_with_matching_filter(self):
        server: PodServer = config.server
        account: Account = server.account
        account_id: UUID = account.account_id
        service_id: int = ADDRESSBOOK_SERVICE_ID
        network: Network = account.network

        account_headers: dict[str, str] = get_account_tls_headers(
            account_id, network.name
        )

        API = BASE_URL + '/v1/pod/member'
        response = requests.get(
            API + f'/service_id/{ADDRESSBOOK_SERVICE_ID}', timeout=120,
            headers=account_headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        member_id = UUID(data['member_id'])
        member_headers = get_member_tls_headers(
            member_id, network.name, service_id
        )

        ws_url = f'{BASE_WS_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

        transport = WebsocketsTransport(
            url=ws_url,
            subprotocols=[WebsocketsTransport.GRAPHQLWS_SUBPROTOCOL],
            headers=member_headers

        )

        client = Client(transport=transport, fetch_schema_from_transport=False)
        session = await client.connect_async(reconnecting=True)

        message = gql({'query_id': str(get_test_uuid())})

        # Test 2: filter for matching relation
        vars = {
            'filters': {'relation': {'eq': 'friend'}}
        }
        task1 = asyncio.create_task(session.execute(message, vars))
        task2 = asyncio.create_task(perform_append(member_id, 'friend'))

        subscribe_result, append_result = await asyncio.gather(task1, task2)

        # Confirm the GraphQL append API call was successful.
        self.assertTrue(bool(append_result))

        # Confirm our update subscription has received the result
        self.assertIsNone(subscribe_result)

        await client.close_async()

    async def test_graphql_websocket_append_with_not_matching_filter(self):
        account = config.server.account
        account_id = account.account_id
        network = account.network

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

        message = gql({'query_id': str(get_test_uuid())})

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
        self.assertTrue(bool(append_friend_result))

        self.assertTrue(append_blah_result)

        # Confirm our update subscription has received the result of the
        # second append
        self.assertTrue(subscribe_result)
        subscribe_data = subscribe_result.get('blah')
        self.assertEqual(
            subscribe_data['action'], 'append'
        )
        self.assertEqual(
            subscribe_data['data']['relation'], 'blah'
        )

        await client.close_async()


async def perform_append(member_id: UUID, relation: str) -> object:
    await asyncio.sleep(1)
    class_name: str = MARKER_NETWORK_LINKS
    service_id: int = ADDRESSBOOK_SERVICE_ID
    network: str = NETWORK
    data_url: str = DATA_API_URL.format(
        protocol='https', fqdn='127.0.0.1', port=8000, service_id=service_id,
        class_name=class_name, action=DataRequestType.APPEND.value
    )

    member_headers = get_member_tls_headers(member_id, network, service_id)

    vars = {
        'member_id': str(get_test_uuid()),
        'relation': relation,
        'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())
    }

    response: HttpResponse = await RestApiClient.call(
        data_url, HttpMethod.POST, data={'data': vars}, timeout=120,
        headers=member_headers
    )
    result = response.json()

    return result


async def perform_delete(member_id: UUID, relation: str) -> object:
    await asyncio.sleep(1)
    class_name: str = MARKER_NETWORK_LINKS
    service_id: int = ADDRESSBOOK_SERVICE_ID
    network: str = NETWORK
    data_url: str = DATA_API_URL.format(
        protocol='https', fqdn='127.0.0.1', port=8000, service_id=service_id,
        class_name=class_name, action=DataRequestType.APPEND.value
    )

    member_headers = get_member_tls_headers(member_id, network, service_id)

    vars = {
        'filters': {'relation': {'eq': relation}},
    }

    response: HttpResponse = await RestApiClient.call(
        data_url, HttpMethod.POST, data={'data': vars}, timeout=120,
        headers=member_headers
    )
    result = response.json()

    return result


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()

