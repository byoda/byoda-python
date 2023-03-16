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
import asyncio
import unittest
import requests

from copy import copy
from uuid import UUID, uuid4
from datetime import datetime, timezone
from multiprocessing import Process

import uvicorn

from byoda.datamodel.account import Account
from byoda.datamodel.graphql_proxy import GraphQlProxy

from byoda.storage.pubsub import PubSubNng

from byoda.util.api_client.graphql_client import GraphQlClient

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.util import get_test_uuid

from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

from tests.lib.auth import get_azure_pod_jwt

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/pod_apis'

_LOGGER = None

POD_ACCOUNT: Account = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        PubSubNng.cleanup()
        network_data = await setup_network(TEST_DIR)
        pod_account = await setup_account(network_data)
        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=config.server.HTTP_PORT)

        app = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [pod_account.tls_secret.common_name], [
                AccountRouter, MemberRouter, AuthTokenRouter,
                AccountDataRouter
            ]
        )

        for account_member in pod_account.memberships.values():
            account_member.enable_graphql_api(app)
            await account_member.update_registration()

        TestDirectoryApis.PROCESS = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={
                'host': '0.0.0.0',
                'port': config.server.HTTP_PORT,
                'log_level': 'trace'
            },
            daemon=True
        )
        TestDirectoryApis.PROCESS.start()

        await asyncio.sleep(3)

    @classmethod
    async def asyncTearDown(self):
        await config.server.shutdown()
        TestDirectoryApis.PROCESS.terminate()

    async def test_graphql_addressbook_jwt(self):
        pod_account = config.server.account
        await pod_account.load_memberships()
        account_member = pod_account.memberships.get(ADDRESSBOOK_SERVICE_ID)
        service_id = ADDRESSBOOK_SERVICE_ID
        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={
                'username': str(account_member.member_id)[:8],
                'password': os.environ['ACCOUNT_SECRET'],
                'service_id': ADDRESSBOOK_SERVICE_ID
            }
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
            url, GRAPHQL_STATEMENTS['network_links']['append'], vars=vars,
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
            url, GRAPHQL_STATEMENTS['network_links']['delete'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()
        data = result.get('data')
        # BUG: This should be 1, but it is 0
        self.assertIsNotNone(data['delete_from_network_links'], 0)
        self.assertIsNone(result.get('errors'))

        vars = {
            'query_id': uuid4(),
            'member_id': AZURE_POD_MEMBER_ID,
            'relation': 'family',
            'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat())

        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['append'], vars=vars,
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

        # add network_link for the 'remote member'
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

        for count in range(1, 100):
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

        self.assertEqual(len(data), 101)

        cursor = ''
        for looper in range(0, 7):
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
            if looper < 6:
                self.assertEqual(len(more_data), 15)
                self.assertEqual(data[looper * 15], more_data[0])
                self.assertEqual(data[looper * 15 + 14], more_data[14])

        self.assertEqual(len(more_data), 11)

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
        self.assertEqual(len(data), 101)

        #
        # Confirm we are not already in the network_links of the Azure pod
        azure_url = f'https://{azure_fqdn}/api/v1/data/service-{service_id}'
        account_member = pod_account.memberships[ADDRESSBOOK_SERVICE_ID]

        response = await GraphQlClient.call(
            azure_url, GRAPHQL_STATEMENTS['network_links']['query'],
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
            query = GRAPHQL_STATEMENTS['network_links']['append']
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
                azure_url, GRAPHQL_STATEMENTS['network_links']['query'],
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
        self.assertGreaterEqual(len(data), 101)

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
        self.assertGreaterEqual(len(data), 104)

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

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['mutate'],
            vars=vars, timeout=120, headers=member_headers
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertEqual(data['mutate_person'], 1)

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['query'],
            vars={'query_id': uuid4()}, timeout=120, headers=member_headers
        )
        data = await response.json()
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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['mutate'], vars=vars,
            timeout=120, headers=member_headers
        )
        data = await response.json()

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
        response = await GraphQlClient.call(
            url, query, vars=vars, timeout=120, headers=member_headers
        )
        data = await response.json()

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['query'], vars=vars,
            timeout=120, headers=alt_member_headers
        )
        result = await response.json()

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['append'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

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

        friend_uuid = get_test_uuid()
        friend_timestamp = str(datetime.now(tz=timezone.utc).isoformat())

        vars = {
            'member_id': str(friend_uuid),
            'relation': 'friend',
            'created_timestamp': friend_timestamp
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['append'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['query'],
            vars={'query_id': uuid4()}, timeout=120, headers=member_headers
        )
        result = await response.json()

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['query'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(len(data['network_links_connection']['edges']), 1)

        vars = {
            'query_id': uuid4(),
            'filters': {'relation': {'eq': 'follow'}},
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['query'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()

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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['query'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()
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
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['update'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(data['update_network_links'], 1)

        vars = {
            'query_id': uuid4(),
            'filters': {'created_timestamp': {'at': friend_timestamp}},
        }

        # Test account data export API for the service
        # service_id = ADDRESSBOOK_SERVICE_ID
        # response = requests.get(
        #     f'{BASE_URL}/v1/pod/account/data/service_id/{service_id}',
        #     headers=account_headers
        # )

        # TODO: refactor data export API for switch from object to SQL storage
        # self.assertEqual(response.status_code, 200)
        # data = response.json()
        # data = data['data']
        # self.assertTrue('member' in data)
        # self.assertTrue('datalogs' in data)
        # self.assertTrue('person' in data)
        # self.assertTrue('network_links' in data)

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['delete'], vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(data['delete_from_network_links'], 1)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
    print('All done!')
