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

from copy import copy
from uuid import uuid4
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.member import Member
from byoda.datamodel.account import Account
from byoda.datamodel.graphql_proxy import GraphQlProxy

from byoda.datatypes import IdType
from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.servers.pod_server import PodServer

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
from tests.lib.setup import get_test_uuid

from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from podserver.codegen.grapqhql_queries_4294929430 \
    import GRAPHQL_STATEMENTS as GRAPHQL_STMTS

from tests.lib.auth import get_azure_pod_jwt
from tests.lib.auth import get_member_auth_header

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/graphql-apis-jwt'

_LOGGER = None

POD_ACCOUNT: Account = None

APP: FastAPI | None = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=True)

        config.test_case = "TEST_CLIENT"
        config.disable_pubsub = True

        server = config.server

        server: PodServer = config.server

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

    async def test_graphql_addressbook_jwt(self):
        account = config.server.account
        service_id = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        password = os.environ['ACCOUNT_SECRET']

        data = {
            'username': str(member.member_id)[:8],
            'password': password,
            'target_type': IdType.MEMBER.value,
            'service_id': ADDRESSBOOK_SERVICE_ID
        }
        url = f'{BASE_URL}/v1/pod/authtoken'
        response: HttpResponse = await ApiClient.call(
            url, method=HttpMethod.POST, data=data, app=APP
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        auth_header = {
            'Authorization': f'bearer {result["auth_token"]}'
        }

        # Test an object
        url = BASE_URL + f'/v1/data/service-{service_id}'

        vars = {
            'given_name': 'Peter',
            'additional_names': '',
            'family_name': 'Hessing',
            'email': 'steven@byoda.org',
            'homepage_url': 'https://byoda.org',
            'avatar_url': 'https://some.place/somewhere'
        }
        class_name: str = 'person'
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.MUTATE],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        field: str = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.MUTATE
        )

        self.assertTrue(field in data)
        self.assertEqual(data[field], 1)

        # Make the given_name parameter optional in the client query
        # for this test
        mutate_person_test = copy(
            GRAPHQL_STMTS[class_name][GraphQlRequestType.MUTATE]
        )
        mutate_person_test.replace(
            '$given_name: String!', '$given_name: String'
        )
        vars = {
            'email': 'steven@byoda.org',
            'family_name': 'Hessing',
        }
        response: HttpResponse = await GraphQlClient.call(
            url, mutate_person_test, vars=vars, timeout=120,
            headers=auth_header, app=APP
        )
        result = response.json()
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.MUTATE
        )
        self.assertEqual(result['data'][field], 1)

        # Try an array of objects that contain an array
        asset_id = uuid4()
        vars = {
            'query_id': uuid4(),
            'asset_id': asset_id,
            'asset_type': "text",
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            ),
            'contents': 'this is a test asset',
            'keywords': ['just', 'a', 'test', 'asset'],
        }
        class_name = 'network_assets'
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        field: str = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.APPEND
        )
        self.assertEqual(data.get(field), 1)

        vars = {
            'filters': {'asset_id': {'eq': str(asset_id)}},
            'query_id': uuid4(),
        }
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        field: str = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        self.assertEqual(data[field]['total_count'], 1)
        network_asset = data[field]['edges'][0]['asset']
        self.assertEqual(len(network_asset['keywords']), 4)

        # add network_link for the 'remote member'
        vars = {
            'query_id': uuid4(),
            'member_id': AZURE_POD_MEMBER_ID,
            'relation': 'friend',
            'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())
        }
        class_name = MARKER_NETWORK_LINKS
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        azure_member_auth_header, azure_fqdn = await get_azure_pod_jwt(
            account, TEST_DIR
        )

        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS['person'][GraphQlRequestType.QUERY],
            timeout=120, vars={'query_id': uuid4()},
            headers=azure_member_auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNone(data)
        self.assertIsNotNone(result.get('errors'))

        vars = {
            'filters': {'member_id': {'eq': str(AZURE_POD_MEMBER_ID)}},
            'query_id': uuid4()
        }
        class_name: str = MARKER_NETWORK_LINKS
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.DELETE],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()
        data = result.get('data')
        field: str = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.DELETE
        )

        self.assertEqual(data[field], 1)
        self.assertIsNone(result.get('errors'))

        vars = {
            'query_id': uuid4(),
            'member_id': AZURE_POD_MEMBER_ID,
            'relation': 'family',
            'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())

        }
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[MARKER_NETWORK_LINKS][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['person'][GraphQlRequestType.QUERY],
            timeout=120, headers=azure_member_auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNone(data)
        self.assertIsNotNone(result.get('errors'))

        asset_id = uuid4()
        vars = {
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            ),
            'asset_type': 'post',
            'asset_id': str(asset_id),
            'creator': 'Pod API Test',
            'created': str(datetime.now(tz=timezone.utc).isoformat()),
            'title': 'test asset',
            'subject': 'just a test asset',
            'contents': 'some utf-8 markdown string',
            'keywords': ["just", "testing"]
        }
        class_name = 'network_assets'
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        field: str = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.APPEND
        )
        self.assertEqual(data[field], 1)
        self.assertIsNone(result.get('errors'))

        # Reuse existing data with specific changes as we need
        # to submit the full object to update an object in NoSql
        # systems
        vars['filters'] = {'asset_id': {'eq': str(asset_id)}}
        vars['contents'] = 'more utf-8 markdown strings'
        vars['keywords'] = ["more", "tests"]

        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.UPDATE],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        field: str = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.UPDATE
        )

        self.assertIsNotNone(data[field])
        self.assertEqual(data[field], 1)

        for count in range(1, 200):
            vars = {
                'query_id': uuid4(),
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                ),
                'asset_type': 'post',
                'asset_id': str(asset_id),
                'creator': f'test account #{count}',
                'created': str(datetime.now(tz=timezone.utc).isoformat()),
                'title': 'test asset',
                'subject': 'just a test asset',
                'contents': 'some utf-8 markdown string',
                'keywords': ["just", "testing"]
            }

            response: HttpResponse = await GraphQlClient.call(
                url,
                GRAPHQL_STMTS['network_assets'][GraphQlRequestType.APPEND],
                vars=vars, timeout=120, headers=auth_header, app=APP
            )
            result = response.json()
            self.assertIsNone(result.get('errors'))

        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['network_assets'][GraphQlRequestType.QUERY],
            timeout=120, vars={'query_id': uuid4()}, headers=auth_header,
            app=APP
        )
        result = response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']

        self.assertEqual(len(data), 201)

        cursor = ''
        for looper in range(0, 14):
            vars = {
                'query_id': uuid4(),
                'first': 15,
                'after': cursor
            }
            response: HttpResponse = await GraphQlClient.call(
                url, GRAPHQL_STMTS['network_assets'][GraphQlRequestType.QUERY],
                vars=vars, timeout=120, headers=auth_header, app=APP
            )
            result = response.json()

            self.assertIsNone(result.get('errors'))
            more_data = result['data']['network_assets_connection']['edges']
            cursor = more_data[-1]['cursor']
            if looper < 13:
                self.assertEqual(len(more_data), 15)
                self.assertEqual(data[looper * 15], more_data[0])
                self.assertEqual(data[looper * 15 + 14], more_data[14])

        self.assertEqual(len(more_data), 6)

        #
        # First query with depth = 1 shows only local results
        # because the remote pod has no entry in network_links with
        # relation 'family' for us
        #
        vars = {
            'query_id': uuid4(),
            'depth': 1,
            'relations': ["family"]
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        data = result['data'][field]['edges']
        self.assertGreaterEqual(len(data), 201)

        #
        # Confirm we are not already in the network_links of the Azure pod
        azure_url = f'https://{azure_fqdn}/api/v1/data/service-{service_id}'
        member = account.memberships[ADDRESSBOOK_SERVICE_ID]

        class_name = MARKER_NETWORK_LINKS
        query: str = GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY]
        response: HttpResponse = await GraphQlClient.call(
            azure_url, query, vars={'query_id': uuid4()}, timeout=120,
            headers=azure_member_auth_header
        )
        result = response.json()
        data = result.get('data')
        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        edges = data[field]['edges']
        filtered_edges = [
            edge for edge in edges
            if edge['network_link']['member_id'] == member.member_id
        ]
        link_to_us = None
        if filtered_edges:
            link_to_us = filtered_edges[0]

        if not link_to_us:
            vars = {
                'query_id': uuid4(),
                'member_id': str(member.member_id),
                'relation': 'family',
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                )
            }
            query = GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND]
            response: HttpResponse = await GraphQlClient.call(
                azure_url, query, vars=vars, timeout=120,
                headers=azure_member_auth_header
            )
            result = response.json()

            data = result.get('data')
            self.assertIsNotNone(data)
            self.assertIsNone(result.get('errors'))

            # Confirm we have a network_link entry
            response: HttpResponse = await GraphQlClient.call(
                azure_url,
                GRAPHQL_STMTS[MARKER_NETWORK_LINKS][GraphQlRequestType.QUERY],
                vars={'query_id': uuid4()}, timeout=120,
                headers=azure_member_auth_header
            )
            result = response.json()
            data = result.get('data')
            self.assertIsNone(result.get('errors'))
            field = GraphQlClient.get_field_label(
                MARKER_NETWORK_LINKS, GraphQlRequestType.QUERY
            )
            edges = data[field]['edges']
            self.assertGreaterEqual(len(edges), 1)
            filtered_edges = [
                edge for edge in edges
                if edge['network_link']['member_id'] == str(
                    member.member_id
                )
            ]
            link_to_us = None
            if filtered_edges:
                link_to_us = filtered_edges[0]
            self.assertIsNotNone(filtered_edges)

        vars = {
            'query_id': uuid4(),
            'depth': 0,
        }
        class_name = 'network_assets'
        response: HttpResponse = await GraphQlClient.call(
            azure_url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, headers=azure_member_auth_header
        )
        result = response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        if not data[field]['total_count']:
            asset_id = uuid4()
            vars = {
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                ),
                'asset_type': 'post',
                'asset_id': str(asset_id),
                'creator': 'Azure Pod API Test',
                'created': str(datetime.now(tz=timezone.utc).isoformat()),
                'title': 'Azure POD test asset',
                'subject': 'just an Azure POD test asset',
                'contents': 'some utf-8 markdown string in Azure',
                'keywords': ["azure", "just", "testing"]
            }

            response: HttpResponse = await GraphQlClient.call(
                azure_url,
                GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
                vars=vars, timeout=120, headers=azure_member_auth_header
            )
            result = response.json()
            data = result.get('data')
            self.assertIsNotNone(data)
            self.assertIsNone(result.get('errors'))

        vars = {
            'depth': 0,
            'query_id': uuid4(),
        }
        response: HttpResponse = await GraphQlClient.call(
            azure_url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, headers=azure_member_auth_header
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        edges = data[field]['edges']
        self.assertGreaterEqual(len(edges), 1)

        #
        # Now we do the query for network assets to our pod with depth=1
        vars = {
            'query_id': uuid4(),
            'depth': 1,
            'relations': ["family"]
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS['network_assets'][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']
        self.assertGreaterEqual(len(data), 202)

        #
        # Now we make sure the local pod and the Azure pod have data for
        # the Person object
        #
        # First the local pod
        vars = {
            'given_name': 'Steven',
            'additional_names': '',
            'family_name': 'Hessing',
            'email': 'steven@byoda.org',
            'homepage_url': 'https://byoda.org',
            'avatar_url': 'https://some.place/somewhere'
        }
        class_name = 'person'
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.MUTATE],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.MUTATE
        )
        self.assertTrue('mutate_person' in data)
        self.assertEqual(data['mutate_person'], 1)

        # Then the Azure pod
        vars = {
            'given_name': 'Stefke',
            'additional_names': '',
            'family_name': 'Hessing',
            'email': 'stevenhessing@live.com',
            'homepage_url': 'https://byoda.org',
            'avatar_url': 'https://some.place/somewhere'
        }
        class_name = 'person'
        response: HttpResponse = await GraphQlClient.call(
            azure_url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.MUTATE],
            vars=vars, timeout=120, headers=azure_member_auth_header
        )
        result = response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.MUTATE
        )
        self.assertEqual(data[field], 1)

        vars = {
            'query_id': uuid4(),
            'depth': 1
        }
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['person'][GraphQlRequestType.QUERY],
            timeout=120, vars=vars, headers=auth_header, app=APP
        )
        data = response.json()
        self.assertIsNotNone(data.get('data'))
        self.assertIsNone(data.get('errors'))

        #
        # Let's send network invites. First we invite ourself
        # and then we invite the Azure pod
        #
        vars = {
            'member_id': str(member.member_id),
            'relation': 'friend',
            'text': 'I am my own best friend',
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            ),
        }
        class_name = 'network_invites'
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS['network_invites'][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        body = response.json()
        data = body.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(body.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.APPEND
        )
        self.assertEqual(data[field], 1)

        vars = {
            'query_id': uuid4(),
            'member_id': str(member.member_id),
            'relation': 'friend',
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            ),
            'text': 'hello, do you want to be my friend?',
            'remote_member_id': AZURE_POD_MEMBER_ID,
            'depth': 1
        }
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS['network_invites'][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        body = response.json()
        data = body.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(body.get('errors'))
        self.assertEqual(data['append_network_invites'], 1)

        class_name: str = 'datalogs'
        response: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=5, headers=auth_header, app=APP
        )
        body = response.json()
        data = body.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(body.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        data = data[field]
        self.assertGreater(data['total_count'], 100)

        #
        # Recursive query test
        #
        graphql_proxy: GraphQlProxy = GraphQlProxy(member)
        relations: list[str] = ['family']
        depth: int = 2
        filters: None = None
        timestamp: datetime = datetime.now(tz=timezone.utc)
        origin_member_id: str = str(member.member_id)
        origin_signature: str = graphql_proxy.create_signature(
            ADDRESSBOOK_SERVICE_ID, relations, filters, timestamp,
            origin_member_id
        )
        vars = {
            'query_id': uuid4(),
            'depth': depth,
            'relations': relations,
            'filters': filters,
            'timestamp': timestamp,
            'origin_member_id': origin_member_id,
            'origin_signature': origin_signature,
        }
        class_name: str = 'network_assets'
        query = GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY]
        response: HttpResponse = await GraphQlClient.call(
            url, query,
            vars=vars, timeout=600, headers=auth_header, app=APP
        )
        result = response.json()

        field: str = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )

        self.assertIsNone(result.get('errors'))
        data = result['data'][field]['edges']
        self.assertGreaterEqual(len(data), 204)

    async def test_graphql_addressbook_claims(self):
        service_id = ADDRESSBOOK_SERVICE_ID
        auth_header = await get_member_auth_header(service_id, app=APP)

        url = BASE_URL + f'/v1/data/service-{service_id}'

        # Create a network asset
        asset_id = get_test_uuid()
        vars = {
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            ),
            'asset_type': 'post',
            'asset_id': str(asset_id),
            'creator': 'Pod API Test',
            'created': str(datetime.now(tz=timezone.utc).isoformat()),
            'title': 'test asset',
            'subject': 'just a test asset',
            'contents': 'some utf-8 markdown string',
            'keywords': ["just", "testing"]
        }

        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['public_assets'][GraphQlRequestType.APPEND],
            vars=vars,
            timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertEqual(data['append_public_assets'], 1)

        # Create a claim for the asset
        vars = {
            'claim_id': get_test_uuid(),
            'claims': ['non-violent'],
            'issuer_id': get_test_uuid(),
            'issuer_type': 'app',
            'object_type': 'network_asset',
            'keyfield': 'asset_id',
            'keyfield_id': asset_id,
            'object_fields': [
                'creator', 'asset_id', 'asset_type', 'title',
                'subject', 'contents', 'keywords'
            ],
            'requester_id': get_test_uuid(),
            'requester_type': 'member',
            'signature': 'bollocks',
            'signature_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            ),
            'signature_format_version': '0.0.0',
            'signature_url': 'https://no.content/',
            'renewal_url': 'https://no.content/',
            'confirmation_url': 'https://no.content/',
            'cert_fingerprint': 'aa00',
            'cert_expiration': str(datetime.now(tz=timezone.utc).isoformat()),
        }
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['public_claims'][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertTrue('append_public_claims' in data)
        self.assertEqual(data['append_public_claims'], 1)

        # Create a thumbnail for the asset
        vars = {
            'thumbnail_id': get_test_uuid(),
            'url': 'https://go.to/thumbnail',
            'height': 360,
            'width': 640,
            'preference': 'default',
            'video_id': asset_id,
        }
        class_name: str = 'public_video_thumbnails'
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertTrue('append_public_video_thumbnails' in data)
        self.assertEqual(data['append_public_video_thumbnails'], 1)

        # Create a chapter for the asset
        vars = {
            'chapter_id': get_test_uuid(),
            'start': 0,
            'end': 300,
            'title': 'some chapter title',
            'video_id': asset_id,
        }
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['public_video_chapters'][GraphQlRequestType.APPEND],
            vars=vars, timeout=120, headers=auth_header, app=APP
        )
        result = response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertTrue('append_public_video_chapters' in data)
        self.assertEqual(data['append_public_video_chapters'], 1)

        # Get the asset with its claim
        vars = {
            'filters': {'asset_id': {'eq': str(asset_id)}},
            'query_id': uuid4(),
        }

        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['public_assets'][GraphQlRequestType.QUERY],
            vars=vars, timeout=1200, headers=auth_header, app=APP
        )
        result = response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertEqual(data['public_assets_connection']['total_count'], 1)
        public_asset = data['public_assets_connection']['edges'][0]['asset']

        self.assertEqual(len(public_asset['public_claims']), 1)
        self.assertEqual(
            public_asset['public_claims'][0]['claims'], ['non-violent']
        )

        self.assertEqual(len(public_asset['public_video_thumbnails']), 1)
        self.assertEqual(
            public_asset['public_video_thumbnails'][0]['preference'], 'default'
        )

        self.assertEqual(len(public_asset['public_video_chapters']), 1)
        self.assertEqual(
            public_asset['public_video_chapters'][0]['title'],
            'some chapter title'
        )

        # Confirm that there is a claim for the asset
        vars = {
            'filters': {'keyfield_id': {'eq': str(asset_id)}},
            'query_id': uuid4(),
        }
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['public_claims'][GraphQlRequestType.QUERY],
            vars=vars, timeout=1200, headers=auth_header, app=APP
        )
        result = response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertEqual(data['public_claims_connection']['total_count'], 1)

        # Delete the asset with its claim
        vars = {
            'filters': {'asset_id': {'eq': str(asset_id)}},
            'query_id': uuid4(),
        }

        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['public_assets'][GraphQlRequestType.DELETE],
            vars=vars, timeout=1200, headers=auth_header, app=APP
        )
        result = response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertEqual(data['delete_from_public_assets'], 1)

        # Confirm the claim for the asset no longer exists
        vars = {
            'filters': {'keyfield_id': {'eq': str(asset_id)}},
            'query_id': uuid4(),
        }
        response: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS['public_claims'][GraphQlRequestType.QUERY],
            vars=vars,
            timeout=1200, headers=auth_header, app=APP
        )
        result = response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        # TODO: this test case is forward-looking when deletes also delete all
        # data linked to the deleted objects
        self.assertEqual(data['public_claims_connection']['total_count'], 1)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
