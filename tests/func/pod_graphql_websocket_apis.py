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
import unittest
import requests

from uuid import UUID
from datetime import datetime, timezone

import orjson
import websockets

from byoda.datamodel.account import Account
from byoda.datamodel.network import Network

from byoda.datastore.data_store import DataStoreType

from byoda.util.api_client.graphql_client import GraphQlClient
from byoda.util.api_client.graphql_client import GraphQlWsClient

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.util import get_test_uuid
from tests.lib.setup import get_account_id

from tests.lib.defines import BASE_URL
from tests.lib.defines import BASE_WS_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

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
            ]
        )

        for account_member in account.memberships.values():
            account_member.enable_graphql_api(app)

    @classmethod
    async def asyncTearDown(self):
        pass

    async def test_graphql_addressbook_tls_cert(self):
        pod_account = config.server.account
        account_id = pod_account.account_id
        network = pod_account.network
        url = f'{BASE_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

        service_id = ADDRESSBOOK_SERVICE_ID

        account_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={account_id}.accounts.{network.name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.name}'
        }

        API = BASE_URL + '/v1/pod/member'
        response = requests.get(
            API + f'/service_id/{service_id}', timeout=120,
            headers=account_headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        member_id = UUID(data['member_id'])

        member_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={member_id}.members-{ADDRESSBOOK_SERVICE_ID}.{NETWORK}',
            'X-Client-SSL-Issuing-CA': f'CN=members-ca.{NETWORK}'
        }

        ws_url = f'{BASE_WS_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

        request = '''
query user {
    name
    age
}
'''
        ws_url = 'ws://127.0.0.1:8000/graphql'
        # '/api/ws/v1/data/service-4294929430'
        async with websockets.connect(
                ws_url, subprotocols=['graphql-transport-ws', 'graphql-ws'],
                extra_headers=member_headers) as websocket:
            query = GraphQlWsClient.prep_query(
                request
            )
            message = orjson.dumps(query)
            await websocket.send(message)
            async for response_message in websocket:
                response_body = orjson.loads(response_message)
                if response_body['type'] == 'connection_ack':
                    _LOGGER.info('the server accepted the connection')
                elif response_body['type'] == 'ka':
                    _LOGGER.info('the server sent a keep alive message')
                else:
                    print(response_body['payload'])

        # client = GraphQlClient(endpoint=ws_url)
        vars = {
            'member_id': str(get_test_uuid()),
            'relation': 'follow',
            'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['append'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
