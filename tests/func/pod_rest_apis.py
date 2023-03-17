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

import orjson

import requests

from uuid import uuid4

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.network import Network

from byoda.datastore.data_store import DataStoreType

from byoda.util.api_client.graphql_client import GraphQlClient

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.setup import setup_network

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import ADDRESSBOOK_VERSION

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

# This must match the test directory in tests/lib/testserver.p
TEST_DIR = '/tmp/byoda-tests/podserver'

_LOGGER = None

POD_ACCOUNT: Account = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        network_data = await setup_network(delete_tmp_dir=False)

        config.test_case = "TEST_CLIENT"

        network: Network = config.server.network
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        with open(f'{network_data["root_dir"]}/account_id', 'rb') as file_desc:
            network_data['account_id'] = orjson.loads(file_desc.read())

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

    async def test_pod_rest_api_tls_client_cert(self):
        pod_account = config.server.account
        account_id = pod_account.account_id
        network = pod_account.network

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
        self.assertEqual(data['root_directory'], '/tmp/byoda-tests/podserver')
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
        self.assertEqual(response.status_code, 200)

    async def test_service_auth(self):
        '''
        Test calling the GraphQL API of the pod with
        the TLS client secret of the Service
        '''

        pod_account: Account = config.server.account
        network: Network = pod_account.network

        service_id = ADDRESSBOOK_SERVICE_ID
        service_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN=service.service-{service_id}.byoda.net',
            'X-Client-SSL-Issuing-CA':
                f'CN=service-ca.service-ca-{service_id}.{network.name}'
        }

        url = f'{BASE_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['query'],
            vars={'query_id': uuid4()}, timeout=120, headers=service_headers
        )
        result = await response.json()

        data = result.get('data')

        # We didn't populate the pod with data yet so
        # we expect an empty result
        self.assertIsNotNone(data.get('person_connection'))

        # Errors would indicate permission issues
        self.assertIsNone(result.get('errors'))

    async def test_pod_rest_api_jwt(self):

        pod_account = config.server.account
        account_id = pod_account.account_id
        await pod_account.load_memberships()
        service_id = ADDRESSBOOK_SERVICE_ID
        account_member: Member = pod_account.memberships.get(service_id)

        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={
                'username': str(account_member.member_id)[:8],
                'password': os.environ['ACCOUNT_SECRET'],
                'service_id': ADDRESSBOOK_SERVICE_ID
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        member_auth_header = {
            'Authorization': f'bearer {data["auth_token"]}'
        }

        API = BASE_URL + '/v1/pod/account'
        response = requests.get(API, timeout=120, headers=member_auth_header)
        # Test fails because account APIs can not be called with JWT
        self.assertEqual(response.status_code, 403)

        #
        # Now we get an account-JWT with basic auth
        #
        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={
                'username': str(pod_account.account_id)[:8],
                'password': os.environ['ACCOUNT_SECRET']
            }
        )
        self.assertEqual(response.status_code, 200)
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
        self.assertEqual(data['root_directory'], '/tmp/byoda-tests/podserver')
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

    async def test_auth_token_request(self):
        pod_account = config.server.account
        await pod_account.load_memberships()
        account_member = pod_account.memberships.get(ADDRESSBOOK_SERVICE_ID)
        password = os.environ['ACCOUNT_SECRET']

        # First we get an account JWT
        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={
                'username': str(pod_account.account_id)[:8],
                'password': password,
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        account_jwt = data.get('auth_token')
        self.assertTrue(isinstance(account_jwt, str))
        auth_header = {
            'Authorization': f'bearer {account_jwt}'
        }
        # Now we get a member JWT by using the account JWT
        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{ADDRESSBOOK_SERVICE_ID}',
            headers=auth_header
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(isinstance(data.get("auth_token"), str))

        # and then we get a member JWT using username/password
        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={
                'username': str(account_member.member_id)[:8],
                'password': password,
                'service_id': ADDRESSBOOK_SERVICE_ID
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        account_jwt = data.get('auth_token')
        self.assertTrue(isinstance(account_jwt, str))
        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={'username': '', 'password': ''}
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertTrue('auth_token' not in data)

        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={
                'username': 'wrong',
                'password': os.environ['ACCOUNT_SECRET'],
                'service_id': ADDRESSBOOK_SERVICE_ID
            }
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertTrue('auth_token' not in data)

        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={
                'username': str(account_member.member_id)[:8],
                'password': 'wrong',
                'service_id': ADDRESSBOOK_SERVICE_ID
            }
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertTrue('auth_token' not in data)

        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={
                'username': 'wrong',
                'password': 'wrong',
                'service_id': ADDRESSBOOK_SERVICE_ID
            }
        )
        data = response.json()
        self.assertEqual(response.status_code, 401)
        self.assertTrue('auth_token' not in data)

        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken',
            json={
                'username': '',
                'password': '',
                'service_id': ADDRESSBOOK_SERVICE_ID
            }
        )
        data = response.json()
        self.assertEqual(response.status_code, 401)
        self.assertTrue('auth_token' not in data)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
