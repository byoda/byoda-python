#!/usr/bin/env python3

'''
Test the POD REST and GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import sys
import unittest

from uuid import UUID, uuid4
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.network import Network

from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.util.api_client.graphql_client import GraphQlClient
from byoda.util.api_client.graphql_client import GraphQlRequestType
from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.restapi_client import HttpMethod

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
from tests.lib.util import get_test_uuid

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from podserver.codegen.grapqhql_queries_4294929430 \
    import GRAPHQL_STATEMENTS as GRAPHQL_STMTS

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/graphql-apis-tls'

POD_ACCOUNT: Account = None

APP: FastAPI | None = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=True)

        config.test_case = "TEST_CLIENT"
        config.disable_pubsub = True

        server = config.server

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

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
            await member.enable_data_apis(APP)

    @classmethod
    async def asyncTearDown(self):
        await GraphQlClient.close_all()

    async def test_graphql_addressbook_tls_cert(self):
        account = config.server.account
        account_id = account.account_id
        network: Network = account.network
        url = f'{BASE_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

        service_id = ADDRESSBOOK_SERVICE_ID

        account_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={account_id}.accounts.{network.name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.name}'
        }

        API = BASE_URL + '/v1/pod/member'
        response: HttpResponse = await ApiClient.call(
            API + f'/service_id/{service_id}', method=HttpMethod.GET,
            timeout=120, headers=account_headers, app=APP
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
        class_name: str = 'person'
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.MUTATE],
            vars=vars, timeout=120, headers=member_headers, app=APP
        )
        result = response.json()

        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        field: str = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.MUTATE
        )
        self.assertEqual(data[field], 1)

        query: str = GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY]
        query = query.replace('\n', '')

        response: HttpResponse = await GraphQlClient.call(
            url, query, vars={'query_id': uuid4()}, timeout=120,
            headers=member_headers, app=APP
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
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.MUTATE],
            vars=vars, timeout=120, headers=member_headers, app=APP
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
            url, query, vars=vars, timeout=120, headers=member_headers,
            app=APP
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
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, headers=alt_member_headers, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNone(data)
        self.assertIsNotNone(result.get('errors'))

        vars = {
            'member_id': str(get_test_uuid()),
            'relation': 'follow',
            'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())
        }
        class_name = MARKER_NETWORK_LINKS
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=member_headers, app=APP
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
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=member_headers, app=APP
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
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=member_headers, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars={'query_id': uuid4()}, timeout=120, headers=member_headers,
            app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        field: str = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        data = result['data'][field]['edges']
        self.assertNotEqual(data[0], data[1])
        self.assertNotEqual(data[1], data[2])

        vars = {
            'query_id': uuid4(),
            'filters': {'relation': {'eq': 'friend'}},
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, headers=member_headers, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(len(data[field]['edges']), 1)

        vars = {
            'query_id': uuid4(),
            'filters': {'relation': {'eq': 'follow'}},
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, headers=member_headers, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        edges = data[field]['edges']
        self.assertEqual(len(edges), 2)
        self.assertNotEqual(edges[0], edges[1])

        vars = {
            'query_id': uuid4(),
            'filters': {'created_timestamp': {'at': friend_timestamp}},
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, headers=member_headers, app=APP
        )
        result = response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        edges = data[field]['edges']
        self.assertEqual(len(edges), 1)
        self.assertEqual(
            edges[0]['network_link']['relation'], 'friend'
        )

        vars = {
            'filters': {'member_id': {'eq': str(friend_uuid)}},
            'relation': 'best_friend',
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.UPDATE],
            vars=vars, timeout=120, headers=member_headers, app=APP
        )
        result = response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.UPDATE
        )
        self.assertEqual(data[field], 1)

        vars = {
            'query_id': uuid4(),
            'filters': {'created_timestamp': {'at': friend_timestamp}},
        }

        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.DELETE],
            vars=vars, timeout=120, headers=member_headers, app=APP
        )
        result = response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(data['delete_from_network_links'], 1)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
