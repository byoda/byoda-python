#!/usr/bin/env python3

'''
Test the POD REST and GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import os
import sys
import asyncio
import unittest
import requests

from datetime import datetime, timezone
from uuid import UUID, uuid4

from multiprocessing import Process
import uvicorn

from requests.auth import HTTPBasicAuth

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.util.api_client.graphql_client import GraphQlClient

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account
from podserver.routers import member
from podserver.routers import authtoken


from tests.lib.setup import get_test_uuid, setup_network

from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import ADDRESSBOOK_VERSION

from tests.lib.graphql_queries import QUERY_PERSON
from tests.lib.graphql_queries import MUTATE_PERSON
from tests.lib.graphql_queries import QUERY_NETWORK
from tests.lib.graphql_queries import APPEND_NETWORK
from tests.lib.graphql_queries import UPDATE_NETWORK_RELATION
from tests.lib.graphql_queries import DELETE_FROM_NETWORK_WITH_FILTER
from tests.lib.graphql_queries import QUERY_NETWORK_ASSETS
from tests.lib.graphql_queries import APPEND_NETWORK_ASSETS
from tests.lib.graphql_queries import UPDATE_NETWORK_ASSETS
from tests.lib.graphql_queries import APPEND_NETWORK_INVITE

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
        network_data = await setup_network(TEST_DIR)
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        pod_account = Account(network_data['account_id'], server.network)
        await pod_account.paths.create_account_directory()
        await pod_account.load_memberships()

        server.account = pod_account

        pod_account.password = os.environ['ACCOUNT_SECRET']

        await pod_account.create_account_secret()
        await pod_account.create_data_secret()
        await pod_account.register()

        await server.get_registered_services()

        services = list(server.network.service_summaries.values())
        service = [
            service
            for service in services
            if service['name'] == 'addressbook'
        ][0]

        global ADDRESSBOOK_SERVICE_ID
        ADDRESSBOOK_SERVICE_ID = service['service_id']
        global ADDRESSBOOK_VERSION
        ADDRESSBOOK_VERSION = service['version']

        member_id = get_test_uuid()
        await pod_account.join(
            ADDRESSBOOK_SERVICE_ID, ADDRESSBOOK_VERSION, member_id=member_id,
            local_service_contract='addressbook.json'
        )

        app = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [pod_account.tls_secret.common_name],
            [account, member, authtoken]
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

        TestDirectoryApis.PROCESS.terminate()

    def test_pod_rest_api_tls_client_cert(self):
        account = config.server.account
        account_id = account.account_id
        network = account.network

        account_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={account_id}.accounts.{network.name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.name}'
        }

        API = BASE_URL + '/v1/pod/account'
        response = requests.get(API, timeout=120, headers=account_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['account_id'], str(account_id))
        self.assertEqual(data['network'], NETWORK)
        self.assertTrue(data['started'].startswith('202'))
        self.assertEqual(data['cloud'], 'LOCAL')
        self.assertEqual(data['private_bucket'], 'LOCAL')
        self.assertEqual(data['public_bucket'], '/var/www/wwwroot/public')
        self.assertEqual(data['root_directory'], '/tmp/byoda-tests/pod_apis')
        self.assertEqual(data['loglevel'], 'DEBUG')
        self.assertEqual(data['private_key_secret'], 'byoda')
        self.assertEqual(data['bootstrap'], True)
        self.assertEqual(len(data['services']), 1)

        # Get the service ID for the addressbook service
        service_id = None
        version = None
        for service in data['services']:
            if service['name'] == 'addressbook':
                service_id = service['service_id']
                version = service['latest_contract_version']

        self.assertEqual(service_id, ADDRESSBOOK_SERVICE_ID)
        self.assertEqual(version, ADDRESSBOOK_VERSION)

        response = requests.get(
            f'{BASE_URL}/v1/pod/member/service_id/{ADDRESSBOOK_SERVICE_ID}',
            timeout=120, headers=account_headers
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data['account_id'], account_id)
        self.assertEqual(data['network'], 'byoda.net')
        self.assertTrue(isinstance(data['member_id'], str))
        self.assertEqual(data['service_id'], ADDRESSBOOK_SERVICE_ID)
        self.assertEqual(data['version'], ADDRESSBOOK_VERSION)
        self.assertEqual(data['name'], 'addressbook')
        self.assertEqual(data['owner'], 'Steven Hessing')
        self.assertEqual(data['website'], 'https://www.byoda.org/')
        self.assertEqual(data['supportemail'], 'steven@byoda.org')
        self.assertEqual(
            data['description'], ('A simple network to maintain contacts')
        )
        self.assertGreater(len(data['certificate']), 80)
        self.assertGreater(len(data['private_key']), 80)

        response = requests.post(
            (
                f'{BASE_URL}/v1/pod/member/service_id/{service_id}'
                f'/version/{version}'
            ),
            timeout=120, headers=account_headers
        )
        self.assertEqual(response.status_code, 409)

        response = requests.put(
            (
                f'{BASE_URL}/v1/pod/member/service_id/{service_id}'
                f'/version/{version}'
            ),
            timeout=120, headers=account_headers
        )
        self.assertEqual(response.status_code, 409)

    async def test_pod_rest_api_jwt(self):

        account = config.server.account
        account_id = account.account_id
        await account.load_memberships()
        service_id = ADDRESSBOOK_SERVICE_ID
        member: Member = account.memberships.get(service_id)

        #
        # This test fails because a member-JWT can't be used for REST APIs,
        # only for GraphQL APIs
        #
        response = requests.get(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{ADDRESSBOOK_SERVICE_ID}',
            auth=HTTPBasicAuth(
                str(member.member_id)[:8], os.environ['ACCOUNT_SECRET']
            )
        )
        data = response.json()
        member_auth_header = {
            'Authorization': f'bearer {data["auth_token"]}'
        }

        API = BASE_URL + '/v1/pod/account'
        response = requests.get(API, timeout=120, headers=member_auth_header)
        self.assertEqual(response.status_code, 403)

        #
        # Now we get an account-JWT
        #
        response = requests.get(
            BASE_URL + '/v1/pod/authtoken',
            auth=HTTPBasicAuth(
                str(account_id)[:8], os.environ['ACCOUNT_SECRET']
            )
        )
        data = response.json()
        account_auth_header = {
            'Authorization': f'bearer {data["auth_token"]}'
        }

        API = BASE_URL + '/v1/pod/account'
        response = requests.get(API, timeout=120, headers=account_auth_header)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data['account_id'], str(account_id))
        self.assertEqual(data['network'], NETWORK)
        self.assertTrue(data['started'].startswith('202'))
        self.assertEqual(data['cloud'], 'LOCAL')
        self.assertEqual(data['private_bucket'], 'LOCAL')
        self.assertEqual(data['public_bucket'], '/var/www/wwwroot/public')
        self.assertEqual(data['root_directory'], '/tmp/byoda-tests/pod_apis')
        self.assertEqual(data['loglevel'], 'DEBUG')
        self.assertEqual(data['private_key_secret'], 'byoda')
        self.assertEqual(data['bootstrap'], True)
        self.assertEqual(len(data['services']), 1)

        API = BASE_URL + '/v1/pod/member'
        response = requests.get(
            f'{API}/service_id/{ADDRESSBOOK_SERVICE_ID}',
            timeout=120, headers=account_auth_header
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['account_id'], account_id)
        self.assertEqual(data['network'], 'byoda.net')
        self.assertTrue(isinstance(data['member_id'], str))
        self.assertEqual(data['service_id'], ADDRESSBOOK_SERVICE_ID)
        self.assertEqual(data['version'], ADDRESSBOOK_VERSION)
        self.assertEqual(data['name'], 'addressbook')
        self.assertEqual(data['owner'], 'Steven Hessing')
        self.assertEqual(data['website'], 'https://www.byoda.org/')
        self.assertEqual(data['supportemail'], 'steven@byoda.org')
        self.assertEqual(
            data['description'], 'A simple network to maintain contacts'
        )
        self.assertGreater(len(data['certificate']), 80)
        self.assertGreater(len(data['private_key']), 80)

        response = requests.post(
            f'{BASE_URL}/v1/pod/member/service_id/{ADDRESSBOOK_SERVICE_ID}/'
            f'version/{ADDRESSBOOK_VERSION}',
            timeout=120, headers=account_auth_header
        )
        self.assertEqual(response.status_code, 409)

        API = (
            BASE_URL +
            f'/v1/pod/member/upload/service_id/{ADDRESSBOOK_SERVICE_ID}' +
            '/visibility/public/filename/ls.bin'
        )
        response = requests.post(
            API,
            files=[
                (
                    'file', ('ls.bin', open('/bin/ls', 'rb'))
                )
            ],
            timeout=120, headers=member_auth_header
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(
            data['location'], 'http://localhost/public/ls.bin'
        )

    def test_auth_token_request(self):
        account = config.server.account
        account_id = account.account_id
        response = requests.get(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{ADDRESSBOOK_SERVICE_ID}',
            auth=HTTPBasicAuth(
                str(account_id)[:8], os.environ['ACCOUNT_SECRET']
            )
        )
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(isinstance(data.get("auth_token"), str))

        response = requests.get(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{ADDRESSBOOK_SERVICE_ID}'
        )
        data = response.json()
        self.assertEqual(response.status_code, 401)
        self.assertTrue('auth_token' not in data)

        response = requests.get(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{ADDRESSBOOK_SERVICE_ID}',
            auth=HTTPBasicAuth(
                'wrong', os.environ['ACCOUNT_SECRET']
            )
        )
        data = response.json()
        self.assertEqual(response.status_code, 401)
        self.assertTrue('auth_token' not in data)

        response = requests.get(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{ADDRESSBOOK_SERVICE_ID}',
            auth=HTTPBasicAuth(
                str(account_id)[:8], 'wrong'
            )
        )
        data = response.json()
        self.assertEqual(response.status_code, 401)
        self.assertTrue('auth_token' not in data)

        response = requests.get(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{ADDRESSBOOK_SERVICE_ID}',
            auth=HTTPBasicAuth(
                'wrong', 'wrong'
            )
        )
        data = response.json()
        self.assertEqual(response.status_code, 401)
        self.assertTrue('auth_token' not in data)

        response = requests.get(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{ADDRESSBOOK_SERVICE_ID}',
            auth=HTTPBasicAuth(
                '', ''
            )
        )
        data = response.json()
        self.assertEqual(response.status_code, 401)
        self.assertTrue('auth_token' not in data)

    async def test_graphql_addressbook_jwt(self):
        account = config.server.account
        account_id = account.account_id
        service_id = ADDRESSBOOK_SERVICE_ID
        response = requests.get(
            BASE_URL + f'/v1/pod/authtoken/service_id/{service_id}',
            auth=HTTPBasicAuth(
                str(account_id)[:8], os.environ['ACCOUNT_SECRET']
            )
        )
        result = response.json()
        auth_header = {
            'Authorization': f'bearer {result["auth_token"]}'
        }

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
            url, MUTATE_PERSON, vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertTrue('mutate_person' in data)
        self.assertEqual(data['mutate_person']['given_name'], 'Peter')

        # Make the given_name parameter optional in the client query
        # for this test
        mutate_person_test = MUTATE_PERSON.replace(
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
        self.assertIsNotNone(result.get('errors'))

        #
        # JWT for the 'Azure POD' member.
        # Test is obsolete as remote JWTs are no longer accepted
        #

        # add network_link for the 'remote member'
        vars = {
            'member_id': AZURE_POD_MEMBER_ID,
            'relation': 'friend',
            'timestamp': str(datetime.now(tz=timezone.utc).isoformat())
        }
        response = await GraphQlClient.call(
            url, APPEND_NETWORK, vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        azure_member_auth_header, azure_fqdn = await get_azure_pod_jwt(
            account, TEST_DIR
        )

        response = await GraphQlClient.call(
            url, QUERY_PERSON, timeout=120, headers=azure_member_auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNone(data)
        self.assertIsNotNone(result.get('errors'))

        vars = {
            'filters': {'member_id': {'eq': str(AZURE_POD_MEMBER_ID)}},
        }
        response = await GraphQlClient.call(
            url, DELETE_FROM_NETWORK_WITH_FILTER, vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        self.assertEqual(len(data['delete_from_network_links']), 1)
        self.assertEqual(
            data['delete_from_network_links'][0]['relation'], 'friend'
        )

        vars = {
            'member_id': AZURE_POD_MEMBER_ID,
            'relation': 'family',
            'timestamp': str(datetime.now(tz=timezone.utc).isoformat())

        }
        response = await GraphQlClient.call(
            url, APPEND_NETWORK, vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        response = await GraphQlClient.call(
            url, QUERY_PERSON, timeout=120, headers=azure_member_auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNone(data)
        self.assertIsNotNone(result.get('errors'))

        # add network_link for the 'remote member'
        asset_id = uuid4()
        vars = {
            'timestamp': str(datetime.now(tz=timezone.utc).isoformat()),
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
            url, APPEND_NETWORK_ASSETS, vars=vars, timeout=120,
            headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        data = result['data']['append_network_assets']
        self.assertEqual(data['asset_type'], 'post')
        self.assertEqual(data['asset_id'], str(asset_id))
        self.assertEqual(data['creator'], 'Pod API Test')
        self.assertEqual(data['title'], 'test asset')
        self.assertEqual(data['subject'], 'just a test asset')
        self.assertEqual(data['contents'], 'some utf-8 markdown string')
        self.assertEqual(data['keywords'], ['just', 'testing'])

        vars = {
            'filters': {'asset_id': {'eq': str(asset_id)}},
            'contents': 'more utf-8 markdown strings',
            'keywords': ["more", "tests"]
        }
        response = await GraphQlClient.call(
            url, UPDATE_NETWORK_ASSETS, vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        self.assertIsNotNone(data['update_network_assets'])

        data = result['data']['update_network_assets']
        self.assertEqual(data['asset_type'], 'post')
        self.assertEqual(data['asset_id'], str(asset_id))
        self.assertEqual(data['creator'], 'Pod API Test')
        self.assertEqual(data['title'], 'test asset')
        self.assertEqual(data['subject'], 'just a test asset')
        self.assertEqual(data['contents'], 'more utf-8 markdown strings')
        self.assertEqual(data['keywords'], ['more', 'tests'])

        for count in range(1, 100):
            vars = {
                'timestamp': str(datetime.now(tz=timezone.utc).isoformat()),
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
                url, APPEND_NETWORK_ASSETS, vars=vars, timeout=120,
                headers=auth_header
            )
            result = await response.json()
            self.assertIsNone(result.get('errors'))

        response = await GraphQlClient.call(
            url, QUERY_NETWORK_ASSETS, timeout=120, headers=auth_header
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']

        self.assertEqual(len(data), 100)

        cursor = ''
        for looper in range(0, 7):
            vars = {
                'first': 15,
                'after': cursor
            }
            response = await GraphQlClient.call(
                url, QUERY_NETWORK_ASSETS,
                vars=vars, timeout=120, headers=auth_header
            )
            result = await response.json()

            self.assertIsNone(result.get('errors'))
            more_data = result['data']['network_assets_connection']['edges']
            cursor = more_data[-1]['cursor']
            if looper < 6:
                self.assertEqual(len(more_data), 15)
                self.assertEqual(data[looper * 15], more_data[0])
                self.assertEqual(data[looper * 15+14], more_data[14])

        self.assertEqual(len(more_data), 10)

        #
        # First query with depth = 1 shows only local results
        # because the remote pod has no entry in network_links with
        # relation 'family' for us
        #
        vars = {
            'depth': 1,
            'relations': ["family"]
        }
        response = await GraphQlClient.call(
            url, QUERY_NETWORK_ASSETS,
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']
        self.assertEqual(len(data), 100)

        #
        # Confirm we are not already in the network_links of the Azure pod
        azure_url = f'https://{azure_fqdn}/api/v1/data/service-{service_id}'
        member = account.memberships[ADDRESSBOOK_SERVICE_ID]

        response = await GraphQlClient.call(
            azure_url, QUERY_NETWORK, timeout=120,
            headers=azure_member_auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNone(result.get('errors'))
        edges = data['network_links_connection']['edges']
        filtered_edges = [
            edge for edge in edges
            if edge['network_link']['member_id'] == member.member_id
        ]
        link_to_us = None
        if filtered_edges:
            link_to_us = filtered_edges[0]

        if not link_to_us:
            vars = {
                'member_id': str(member.member_id),
                'relation': 'family',
                'timestamp': str(datetime.now(tz=timezone.utc).isoformat())
            }
            response = await GraphQlClient.call(
                azure_url, APPEND_NETWORK, vars=vars, timeout=120,
                headers=azure_member_auth_header
            )
            result = await response.json()

            data = result.get('data')
            self.assertIsNotNone(data)
            self.assertIsNone(result.get('errors'))

            # Confirm we have a network_link entry
            response = await GraphQlClient.call(
                azure_url, QUERY_NETWORK, timeout=120,
                headers=azure_member_auth_header
            )
            result = await response.json()
            data = result.get('data')
            self.assertIsNone(result.get('errors'))
            edges = data['network_links_connection']['edges']
            self.assertGreaterEqual(len(edges), 1)
            filtered_edges = [
                edge for edge in edges
                if edge['network_link']['member_id'] == str(member.member_id)
            ]
            link_to_us = None
            if filtered_edges:
                link_to_us = filtered_edges[0]
            self.assertIsNotNone(filtered_edges)

        vars = {
            'depth': 0,
        }
        response = await GraphQlClient.call(
            azure_url, QUERY_NETWORK_ASSETS,
            vars=vars, timeout=120, headers=azure_member_auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        if not data['network_assets_connection']['total_count']:
            asset_id = uuid4()
            vars = {
                'timestamp': str(datetime.now(tz=timezone.utc).isoformat()),
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
                azure_url, APPEND_NETWORK_ASSETS, vars=vars, timeout=120,
                headers=azure_member_auth_header
            )
            result = await response.json()
            data = result.get('data')
            self.assertIsNotNone(data)
            self.assertIsNone(result.get('errors'))

        vars = {
            'depth': 0,
        }
        response = await GraphQlClient.call(
            azure_url, QUERY_NETWORK_ASSETS,
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
            'depth': 1,
            'relations': ["family"]
        }
        response = await GraphQlClient.call(
            url, QUERY_NETWORK_ASSETS,
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']
        self.assertEqual(len(data), 101)

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
            url, MUTATE_PERSON, vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertTrue('mutate_person' in data)
        self.assertEqual(data['mutate_person']['given_name'], 'Steven')

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
            azure_url, MUTATE_PERSON, vars=vars,
            timeout=120, headers=azure_member_auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(data['mutate_person']['given_name'], 'Stefke')

        vars = {
            'depth': 1
        }
        response = await GraphQlClient.call(
            url, QUERY_PERSON, timeout=120,
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
            'member_id': str(member.member_id),
            'relation': 'friend',
            'text': 'I am my own best friend',
            'timestamp': str(datetime.now(tz=timezone.utc).isoformat()),

        }
        response = await GraphQlClient.call(
            url, APPEND_NETWORK_INVITE, timeout=120,
            vars=vars, headers=auth_header
        )
        body = await response.json()
        data = body.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(body.get('errors'))
        data = data['append_network_invites']
        for key, value in data.items():
            self.assertEqual(value, vars[key])

        vars = {
            'member_id': str(member.member_id),
            'relation': 'friend',
            'timestamp': str(datetime.now(tz=timezone.utc).isoformat()),
            'text': 'hello, do you want to be my friend?',
            'remote_member_id': AZURE_POD_MEMBER_ID,
            'depth': 1
        }
        response = await GraphQlClient.call(
            url, APPEND_NETWORK_INVITE, timeout=120,
            vars=vars, headers=auth_header
        )
        body = await response.json()
        data = body.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(body.get('errors'))
        data = data['append_network_invites']
        for key, value in data.items():
            self.assertEqual(value, vars[key])

    async def test_graphql_addressbook_tls_cert(self):
        account = config.server.account
        account_id = account.account_id
        network = account.network
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
            'given_name': 'Carl',
            'additional_names': '',
            'family_name': 'Hessing',
            'email': 'steven@byoda.org',
            'homepage_url': 'https://byoda.org',
            'avatar_url': 'https://some.place/somewhere'
        }

        response = await GraphQlClient.call(
            url, MUTATE_PERSON,
            vars=vars, timeout=120, headers=member_headers
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertEqual(
            data['mutate_person']['given_name'], 'Carl'
        )

        response = await GraphQlClient.call(
            url, QUERY_PERSON, timeout=120, headers=member_headers
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
            url, MUTATE_PERSON, vars=vars, timeout=120, headers=member_headers
        )
        data = await response.json()

        self.assertIsNotNone(data.get('data'))
        self.assertIsNone(data.get('errors'))
        self.assertEqual(data['data']['mutate_person']['given_name'], 'Steven')

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
        response = await GraphQlClient.call(
            url, QUERY_PERSON, vars=vars, timeout=120,
            headers=alt_member_headers
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
            'timestamp': str(datetime.now(tz=timezone.utc).isoformat())
        }
        response = await GraphQlClient.call(
            url, APPEND_NETWORK, vars=vars, timeout=120, headers=member_headers
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        vars = {
            'member_id': str(get_test_uuid()),
            'relation': 'follow',
            'timestamp': str(datetime.now(tz=timezone.utc).isoformat())
        }
        response = await GraphQlClient.call(
            url, APPEND_NETWORK, vars=vars, timeout=120, headers=member_headers
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
            'timestamp': friend_timestamp
        }
        response = await GraphQlClient.call(
            url, APPEND_NETWORK, vars=vars, timeout=120, headers=member_headers
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        response = await GraphQlClient.call(
            url, QUERY_NETWORK, timeout=120, headers=member_headers
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        data = result['data']['network_links_connection']['edges']
        self.assertNotEqual(data[0], data[1])
        self.assertNotEqual(data[1], data[2])

        vars = {
            'filters': {'relation': {'eq': 'friend'}},
        }
        response = await GraphQlClient.call(
            url, QUERY_NETWORK, vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(len(data['network_links_connection']['edges']), 1)

        vars = {
            'filters': {'relation': {'eq': 'follow'}},
        }
        response = await GraphQlClient.call(
            url, QUERY_NETWORK, vars=vars,
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
            'filters': {'timestamp': {'at': friend_timestamp}},
        }
        response = await GraphQlClient.call(
            url, QUERY_NETWORK, vars=vars,
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
            url, UPDATE_NETWORK_RELATION, vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(
            data['update_network_links']['relation'],
            'best_friend'
        )
        self.assertEqual(
            data['update_network_links']['member_id'], str(friend_uuid)
        )

        vars = {
            'filters': {'timestamp': {'at': friend_timestamp}},
        }
        response = await GraphQlClient.call(
            url, DELETE_FROM_NETWORK_WITH_FILTER, vars=vars,
            timeout=120, headers=member_headers
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        self.assertEqual(len(data['delete_from_network_links']), 1)
        self.assertEqual(
            data['delete_from_network_links'][0]['relation'],
            'best_friend'
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

unittest.main()
