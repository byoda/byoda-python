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
import shutil
import unittest
import requests

from copy import copy
from uuid import uuid4
from datetime import datetime, timezone

from byoda.datamodel.account import Account
from byoda.datamodel.network import Network
from byoda.datamodel.graphql_proxy import GraphQlProxy

from byoda.datatypes import IdType
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
from tests.lib.setup import get_account_id
from tests.lib.setup import get_test_uuid

from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

from tests.lib.auth import get_azure_pod_jwt
from tests.lib.auth import get_member_auth_header

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/podserver'

_LOGGER = None

POD_ACCOUNT: Account = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)

        config.test_case = "TEST_CLIENT"

        network: Network = config.server.network
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        network_data['account_id'] = get_account_id(network_data)

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        if local_service_contract:
            dest = TEST_DIR + '/' + local_service_contract
            dest_dir = os.path.dirname(dest)
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copyfile(
                local_service_contract, TEST_DIR + '/' + local_service_contract
            )

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

    async def test_graphql_addressbook_jwt(self):
        pod_account = config.server.account
        await pod_account.load_memberships()
        account_member = pod_account.memberships.get(ADDRESSBOOK_SERVICE_ID)

        service_id = ADDRESSBOOK_SERVICE_ID
        password = os.environ['ACCOUNT_SECRET']

        data = {
            'username': str(account_member.member_id)[:8],
            'password': password,
            'target_type': IdType.MEMBER.value,
            'service_id': ADDRESSBOOK_SERVICE_ID
        }
        url = f'{BASE_URL}/v1/pod/authtoken'
        response = requests.post(url, json=data)

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['mutate'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertTrue('mutate_person' in data)
        self.assertEqual(data['mutate_person'], 1)

        # Make the given_name parameter optional in the client query
        # for this test
        mutate_person_test = copy(GRAPHQL_STATEMENTS['person']['mutate'])
        mutate_person_test.replace(
            '$given_name: String!', '$given_name: String'
        )
        vars = {
            'email': 'steven@byoda.org',
            'family_name': 'Hessing',
        }
        response = await GraphQlClient.call(
            url, mutate_person_test, vars=vars, timeout=120,
            headers=auth_header
        )
        result = await response.json()
        self.assertEqual(result['data']['mutate_person'], 1)

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['append'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertEqual(data.get('append_network_assets'), 1)

        vars = {
            'filters': {'asset_id': {'eq': str(asset_id)}},
            'query_id': uuid4(),
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['query'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertEqual(data['network_assets_connection']['total_count'], 1)
        network_asset = data['network_assets_connection']['edges'][0]['asset']
        self.assertEqual(len(network_asset['keywords']), 4)

        # add network_link for the 'remote member'
        vars = {
            'query_id': uuid4(),
            'member_id': AZURE_POD_MEMBER_ID,
            'relation': 'friend',
            'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['append'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        azure_member_auth_header, azure_fqdn = await get_azure_pod_jwt(
            pod_account, TEST_DIR
        )

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['query'], timeout=120,
            vars={'query_id': uuid4()}, headers=azure_member_auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNone(data)
        self.assertIsNotNone(result.get('errors'))

        vars = {
            'filters': {'member_id': {'eq': str(AZURE_POD_MEMBER_ID)}},
            'query_id': uuid4()
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['delete'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertEqual(data['delete_from_network_links'], 1)
        self.assertIsNone(result.get('errors'))

        vars = {
            'query_id': uuid4(),
            'member_id': AZURE_POD_MEMBER_ID,
            'relation': 'family',
            'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())

        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['append'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['query'], timeout=120,
            headers=azure_member_auth_header
        )
        result = await response.json()

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

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['append'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertEqual(data['append_network_assets'], 1)
        self.assertIsNone(result.get('errors'))

        vars = {
            'filters': {'asset_id': {'eq': str(asset_id)}},
            'contents': 'more utf-8 markdown strings',
            'keywords': ["more", "tests"]
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['update'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        self.assertIsNotNone(data['update_network_assets'])

        self.assertEqual(result['data']['update_network_assets'], 1)

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

            response = await GraphQlClient.call(
                url, GRAPHQL_STATEMENTS['network_assets']['append'],
                vars=vars, timeout=120, headers=auth_header
            )
            result = await response.json()
            self.assertIsNone(result.get('errors'))

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['query'], timeout=120,
            vars={'query_id': uuid4()}, headers=auth_header
        )
        result = await response.json()

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
            response = await GraphQlClient.call(
                url, GRAPHQL_STATEMENTS['network_assets']['query'],
                vars=vars, timeout=120, headers=auth_header
            )
            result = await response.json()

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['query'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']
        self.assertGreaterEqual(len(data), 201)

        #
        # Confirm we are not already in the network_links of the Azure pod
        azure_url = f'https://{azure_fqdn}/api/v1/data/service-{service_id}'
        account_member = pod_account.memberships[ADDRESSBOOK_SERVICE_ID]

        response = await GraphQlClient.call(
            azure_url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['query'],
            vars={'query_id': uuid4()}, timeout=120,
            headers=azure_member_auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNone(result.get('errors'))
        edges = data['network_links_connection']['edges']
        filtered_edges = [
            edge for edge in edges
            if edge['network_link']['member_id'] == account_member.member_id
        ]
        link_to_us = None
        if filtered_edges:
            link_to_us = filtered_edges[0]

        if not link_to_us:
            vars = {
                'query_id': uuid4(),
                'member_id': str(account_member.member_id),
                'relation': 'family',
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                )
            }
            query = GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['append']
            response = await GraphQlClient.call(
                azure_url, query,
                vars=vars, timeout=120, headers=azure_member_auth_header
            )
            result = await response.json()

            data = result.get('data')
            self.assertIsNotNone(data)
            self.assertIsNone(result.get('errors'))

            # Confirm we have a network_link entry
            response = await GraphQlClient.call(
                azure_url, GRAPHQL_STATEMENTS[MARKER_NETWORK_LINKS]['query'],
                vars={'query_id': uuid4()}, timeout=120,
                headers=azure_member_auth_header
            )
            result = await response.json()
            data = result.get('data')
            self.assertIsNone(result.get('errors'))
            edges = data['network_links_connection']['edges']
            self.assertGreaterEqual(len(edges), 1)
            filtered_edges = [
                edge for edge in edges
                if edge['network_link']['member_id'] == str(
                    account_member.member_id
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
        response = await GraphQlClient.call(
            azure_url, GRAPHQL_STATEMENTS['network_assets']['query'],
            vars=vars, timeout=120, headers=azure_member_auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        if not data['network_assets_connection']['total_count']:
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

            response = await GraphQlClient.call(
                azure_url, GRAPHQL_STATEMENTS['network_assets']['append'],
                vars=vars, timeout=120, headers=azure_member_auth_header
            )
            result = await response.json()
            data = result.get('data')
            self.assertIsNotNone(data)
            self.assertIsNone(result.get('errors'))

        vars = {
            'depth': 0,
            'query_id': uuid4(),
        }
        response = await GraphQlClient.call(
            azure_url, GRAPHQL_STATEMENTS['network_assets']['query'],
            vars=vars, timeout=120, headers=azure_member_auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        edges = data['network_assets_connection']['edges']
        self.assertGreaterEqual(len(edges), 1)

        #
        # Now we do the query for network assets to our pod with depth=1
        vars = {
            'query_id': uuid4(),
            'depth': 1,
            'relations': ["family"]
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['query'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['mutate'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
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
        response = await GraphQlClient.call(
            azure_url, GRAPHQL_STATEMENTS['person']['mutate'], vars=vars,
            timeout=120, headers=azure_member_auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(data['mutate_person'], 1)

        vars = {
            'query_id': uuid4(),
            'depth': 1
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['query'], timeout=120,
            vars=vars, headers=auth_header
        )
        data = await response.json()
        self.assertIsNotNone(data.get('data'))
        self.assertIsNone(data.get('errors'))

        #
        # Let's send network invites. First we invite ourself
        # and then we invite the Azure pod
        #
        vars = {
            'member_id': str(account_member.member_id),
            'relation': 'friend',
            'text': 'I am my own best friend',
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            ),
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_invites']['append'],
            vars=vars, timeout=120, headers=auth_header
        )
        body = await response.json()
        data = body.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(body.get('errors'))
        self.assertEqual(data['append_network_invites'], 1)

        vars = {
            'query_id': uuid4(),
            'member_id': str(account_member.member_id),
            'relation': 'friend',
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            ),
            'text': 'hello, do you want to be my friend?',
            'remote_member_id': AZURE_POD_MEMBER_ID,
            'depth': 1
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_invites']['append'],
            vars=vars, timeout=120, headers=auth_header
        )
        body = await response.json()
        data = body.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(body.get('errors'))
        self.assertEqual(data['append_network_invites'], 1)

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['datalogs']['query'],
            vars=vars, timeout=5, headers=auth_header
        )
        body = await response.json()
        data = body.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(body.get('errors'))
        data = data['datalogs_connection']
        self.assertGreater(data['total_count'], 100)

        #
        # Recursive query test
        #
        graphql_proxy = GraphQlProxy(account_member)
        relations = ['family']
        depth = 2
        filters = None
        timestamp = datetime.now(timezone.utc)
        origin_member_id = str(account_member.member_id)
        origin_signature = graphql_proxy.create_signature(
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
        query = GRAPHQL_STATEMENTS['network_assets']['query']
        response = await GraphQlClient.call(
            url, query,
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']
        self.assertGreaterEqual(len(data), 204)

    async def test_graphql_addressbook_claims(self):
        service_id = ADDRESSBOOK_SERVICE_ID
        auth_header = await get_member_auth_header(service_id)

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

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['public_assets']['append'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertEqual(data['append_public_assets'], 1)
        self.assertIsNone(result.get('errors'))

        # Create a claim for the asset
        vars = {
            'claim_id': get_test_uuid(),
            'claims': ['non-violent'],
            'issuer': get_test_uuid(),
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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['public_claims']['append'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['public_video_thumbnails']['append'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['public_video_chapters']['append'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

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

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['public_assets']['query'], vars=vars,
            timeout=1200, headers=auth_header
        )
        result = await response.json()
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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['public_claims']['query'], vars=vars,
            timeout=1200, headers=auth_header
        )
        result = await response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertEqual(data['public_claims_connection']['total_count'], 1)

        # Delete the asset with its claim
        vars = {
            'filters': {'asset_id': {'eq': str(asset_id)}},
            'query_id': uuid4(),
        }

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['public_assets']['delete'], vars=vars,
            timeout=1200, headers=auth_header
        )
        result = await response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertEqual(data['delete_from_public_assets'], 1)

        # Confirm the claim for the asset no longer exists
        vars = {
            'filters': {'keyfield_id': {'eq': str(asset_id)}},
            'query_id': uuid4(),
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['public_claims']['query'], vars=vars,
            timeout=1200, headers=auth_header
        )
        result = await response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        # TODO: this test case is forward-looking when deletes also delete all
        # data linked to the deleted objects
        self.assertEqual(data['public_claims_connection']['total_count'], 1)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
