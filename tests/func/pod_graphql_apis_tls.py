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

from uuid import UUID, uuid4
from datetime import datetime, timezone

from byoda.util.api_client.api_client import HttpResponse

from byoda.datamodel.account import Account
from byoda.datamodel.network import Network

from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.datastore.data_store import DataStoreType

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
from tests.lib.util import get_test_uuid
from tests.lib.setup import get_account_id

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/podserver'

_LOGGER = None

POD_ACCOUNT: Account = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)

        config.test_case = "TEST_CLIENT"

        network: Network = config.server.network
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

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
            'v0.0.1', [
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

        vars = {
            'query_id': uuid4(),
            'given_name': 'Carl',
            'additional_names': '',
            'family_name': 'Hessing',
            'email': 'steven@byoda.org',
            'homepage_url': 'https://byoda.org',
            'avatar_url': 'https://some.place/somewhere'
        }

        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['mutate'],
            vars=vars, timeout=120, headers=member_headers
        )
        result = response.json()

        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertEqual(data['mutate_person'], 1)

        query: str = GRAPHQL_STATEMENTS['person']['query'].replace('\n', '')
        response: HttpResponse = await GraphQlClient.call(
            url, query, vars={'query_id': uuid4()}, timeout=120,
            headers=member_headers
        )
        data = response.json()
        self.assertIsNotNone(data.get('data'))
        self.assertIsNone(data.get('errors'))

        vars = {
            'given_name': 'Steven',
            'additional_names': '',
            'family_name': 'Hessing',
            'email': 'steven@byoda.org',
            'homepage_url': 'https://byoda.org',
            'avatar_url': 'https://some.place/somewhere'
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['mutate'], vars=vars,
            timeout=120, headers=member_headers
        )
        data = response.json()

        self.assertIsNotNone(data.get('data'))
        self.assertIsNone(data.get('errors'))
        self.assertEqual(data['data']['mutate_person'], 1)

        query = '''
                mutation {
                    mutate_member(
                        member_id: "7a0260ef-7afb-426f-b132-4062ef7636d7",
                        joined: "2021-09-19T09:04:00+07:00"
                    ) {
                        member_id
                    }
                }
        '''
        # Mutation fails because 'member' can only read this data
        vars['query_id'] = uuid4()
        response: HttpResponse = await GraphQlClient.call(
            url, query, vars=vars, timeout=120, headers=member_headers
        )
        data = response.json()

        self.assertIsNone(data.get('data'))
        self.assertIsNotNone(data.get('errors'))

        # Test with cert of another member
        alt_member_id = get_test_uuid()

        alt_member_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={alt_member_id}.members-0.{NETWORK}',
            'X-Client-SSL-Issuing-CA': f'CN=members-ca.{NETWORK}'
        }

        # Query fails because other members do not have access
        vars['query_id'] = uuid4()
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['query'], vars=vars,
            timeout=120, headers=alt_member_headers
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNone(data)
        self.assertIsNotNone(result.get('errors'))

        self.assertIsNone(result['data'])
        self.assertIsNotNone(result['errors'])

        vars = {
            'member_id': str(get_test_uuid()),
            'relation': 'follow',
            'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['append'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        vars = {
            'member_id': str(get_test_uuid()),
            'relation': 'follow',
            'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['append'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        friend_uuid = get_test_uuid()
        friend_timestamp = str(datetime.now(tz=timezone.utc).isoformat())

        vars = {
            'member_id': str(friend_uuid),
            'relation': 'friend',
            'created_timestamp': friend_timestamp
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['append'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['query'],
            vars={'query_id': uuid4()}, timeout=120, headers=member_headers
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        data = result['data']['network_links_connection']['edges']
        self.assertNotEqual(data[0], data[1])
        self.assertNotEqual(data[1], data[2])

        vars = {
            'query_id': uuid4(),
            'filters': {'relation': {'eq': 'friend'}},
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['query'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(len(data['network_links_connection']['edges']), 1)

        vars = {
            'query_id': uuid4(),
            'filters': {'relation': {'eq': 'follow'}},
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['query'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        edges = data['network_links_connection']['edges']
        self.assertEqual(len(edges), 2)
        self.assertNotEqual(edges[0], edges[1])

        vars = {
            'query_id': uuid4(),
            'filters': {'created_timestamp': {'at': friend_timestamp}},
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['query'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        edges = data['network_links_connection']['edges']
        self.assertEqual(len(edges), 1)
        self.assertEqual(
            edges[0]['network_link']['relation'], 'friend'
        )

        vars = {
            'filters': {'member_id': {'eq': str(friend_uuid)}},
            'relation': 'best_friend',
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['update'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(data['update_network_links'], 1)

        vars = {
            'query_id': uuid4(),
            'filters': {'created_timestamp': {'at': friend_timestamp}},
        }

        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['delete'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(data['delete_from_network_links'], 1)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
