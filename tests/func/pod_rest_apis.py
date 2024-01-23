#!/usr/bin/env python3

'''
Test the POD REST and Data APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import sys
import unittest

from uuid import UUID
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.network import Network

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.restapi_client import HttpMethod
from byoda.util.api_client.data_api_client import DataApiClient

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from byoda.exceptions import ByodaRuntimeError

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import ADDRESSBOOK_VERSION

from tests.lib.util import get_test_uuid

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

# This must match the test directory in tests/lib/testserver.p
TEST_DIR = '/tmp/byoda-tests/pod-rest-apis'

APP: FastAPI | None = None


class TestPodApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR)
        network_data: dict[str, str] = await setup_network(delete_tmp_dir=True)

        config.test_case = 'TEST_CLIENT'
        config.disable_pubsub = True

        server: PodServer = config.server

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account: Account = await setup_account(
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
            await member.enable_data_apis(
                APP, server.data_store, server.cache_store
            )

    @classmethod
    async def asyncTearDown(self) -> None:
        await ApiClient.close_all()

    async def test_pod_rest_api_tls_client_cert(self) -> None:
        account: Account = config.server.account
        account_id: UUID = account.account_id
        network: Network = account.network

        account_headers: dict[str, str] = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={account_id}.accounts.{network.name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.name}'
        }

        API: str = BASE_URL + '/v1/pod/account'
        resp: HttpResponse = await ApiClient.call(
            API, method=HttpMethod.GET, timeout=120, headers=account_headers,
            app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data: [str, str] = resp.json()
        self.assertEqual(data['account_id'], str(account_id))
        self.assertEqual(data['network'], NETWORK)
        self.assertTrue(data['started'].startswith('202'))
        self.assertEqual(data['cloud'], 'LOCAL')
        self.assertEqual(data['private_bucket'], 'LOCAL')
        self.assertEqual(data['public_bucket'], '/byoda/public')
        self.assertEqual(data['restricted_bucket'], '/byoda/restricted')
        self.assertEqual(data['root_directory'], TEST_DIR)
        self.assertEqual(data['loglevel'], 'DEBUG')
        self.assertEqual(data['private_key_secret'], 'byoda')
        self.assertEqual(data['bootstrap'], True)
        self.assertTrue(len(data['services']))

        # Get the service ID for the addressbook service
        service_id = None
        version = None
        for service in data['services']:
            if service['name'] == 'addressbook':
                service_id: int = service['service_id']
                version: int = service['latest_contract_version']

        self.assertEqual(service_id, ADDRESSBOOK_SERVICE_ID)
        self.assertEqual(version, ADDRESSBOOK_VERSION)

        resp: HttpResponse = await ApiClient.call(
            f'{BASE_URL}/v1/pod/member/service_id/{ADDRESSBOOK_SERVICE_ID}',
            method=HttpMethod.GET, timeout=120, headers=account_headers,
            app=APP
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertTrue(data['account_id'], account_id)
        self.assertEqual(data['network'], 'byoda.net')
        self.assertTrue(isinstance(data['member_id'], str))
        self.assertEqual(data['service_id'], ADDRESSBOOK_SERVICE_ID)
        self.assertEqual(data['version'], ADDRESSBOOK_VERSION)
        self.assertEqual(data['name'], 'addressbook')
        self.assertEqual(data['owner'], 'Steven Hessing')
        self.assertEqual(data['website'], 'https://addressbook.byoda.org/')
        self.assertEqual(data['supportemail'], 'steven@byoda.org')
        self.assertEqual(
            data['description'], ('A simple network to maintain contacts')
        )
        self.assertGreater(len(data['certificate']), 80)
        self.assertGreater(len(data['private_key']), 80)

        with self.assertRaises(ByodaRuntimeError):
            resp: HttpResponse = await ApiClient.call(
                (
                    f'{BASE_URL}/v1/pod/member/service_id/{service_id}'
                    f'/version/{version}'
                ),
                method=HttpMethod.POST, timeout=120, headers=account_headers,
                app=APP
            )
            self.assertEqual(resp.status_code, 409)

        resp: HttpResponse = await ApiClient.call(
            (
                f'{BASE_URL}/v1/pod/member/service_id/{service_id}'
                f'/version/{version}'
            ),
            method=HttpMethod.PUT, timeout=120, headers=account_headers,
            app=APP
        )
        self.assertEqual(resp.status_code, 200)

    async def test_service_auth(self) -> None:
        '''
        Test calling the Data API of the pod with
        the TLS client secret of the Service
        '''

        server: PodServer = config.server
        service_id: int = ADDRESSBOOK_SERVICE_ID
        account: Account = server.account
        network: Network = account.network
        member: Member = await account.get_membership(service_id)

        # Append some data using a member JWT:
        resp: HttpResponse = await ApiClient.call(
            f'{BASE_URL}/v1/pod/authtoken',
            method=HttpMethod.POST,
            data={
                'username': str(member.member_id)[:8],
                'password': os.environ['ACCOUNT_SECRET'],
                'target_type': IdType.MEMBER.value,
                'service_id': ADDRESSBOOK_SERVICE_ID
            },
            headers={'Content-Type': 'application/json'},
            app=APP
        )

        self.assertEqual(resp.status_code, 200)
        data: dict[str, str] = resp.json()
        member_auth_header: dict[str, str] = {
            'Authorization': f'bearer {data["auth_token"]}'
        }

        person_data: dict[str, str] = {
            'data': {
                'email': 'steven@byoda.org',
                'family_name': 'Hessing',
                'given_name': 'Steven',
            }
        }
        class_name: str = 'person'

        resp: HttpResponse = await DataApiClient.call(
            service_id, class_name, DataRequestType.MUTATE,
            headers=member_auth_header,
            data=person_data, app=APP
        )
        self.assertEqual(resp.status_code, 200)

        service_headers: dict[str, str] = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN=service.service-{service_id}.byoda.net',
            'X-Client-SSL-Issuing-CA':
                f'CN=service-ca.service-ca-{service_id}.{network.name}'
        }

        self.assertEqual(resp.status_code, 200)

        resp = await DataApiClient.call(
            service_id, class_name, DataRequestType.QUERY,
            headers=service_headers, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data['total_count'], 1)

    async def test_pod_rest_api_jwt(self) -> None:

        account: Account = config.server.account
        account_id: UUID = account.account_id
        await account.load_memberships()
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = account.memberships.get(service_id)

        resp: HttpResponse = await ApiClient.call(
            f'{BASE_URL}/v1/pod/authtoken',
            method=HttpMethod.POST,
            data={
                'username': str(member.member_id)[:8],
                'password': os.environ['ACCOUNT_SECRET'],
                'target_type': IdType.MEMBER.value,
                'service_id': ADDRESSBOOK_SERVICE_ID
            },
            headers={'Content-Type': 'application/json'},
            app=APP
        )

        self.assertEqual(resp.status_code, 200)
        data: dict[str, str] = resp.json()
        member_auth_header: dict[str, str] = {
            'Authorization': f'bearer {data["auth_token"]}'
        }

        API: str = BASE_URL + '/v1/pod/account'
        with self.assertRaises(ByodaRuntimeError):
            resp = await ApiClient.call(
                API, method=HttpMethod.GET, timeout=120,
                headers=member_auth_header, app=APP
            )
            # Test fails because account APIs can not be called with JWT
            self.assertEqual(resp.status_code, 403)

        #
        # Now we get an account-JWT with basic auth
        #
        resp = await ApiClient.call(
            f'{BASE_URL}/v1/pod/authtoken',
            method=HttpMethod.POST,
            data={
                'username': str(account.account_id)[:8],
                'password': os.environ['ACCOUNT_SECRET'],
                'target_type': IdType.ACCOUNT.value,
            },
            app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        account_auth_header: dict[str, str] = {
            'Authorization': f'bearer {data["auth_token"]}'
        }

        API = BASE_URL + '/v1/pod/account'
        resp = await ApiClient.call(
            API, method=HttpMethod.GET, timeout=120,
            headers=account_auth_header, app=APP
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data['account_id'], str(account_id))
        self.assertEqual(data['network'], NETWORK)
        self.assertTrue(data['started'].startswith('202'))
        self.assertEqual(data['cloud'], 'LOCAL')
        self.assertEqual(data['private_bucket'], 'LOCAL')
        self.assertEqual(data['public_bucket'], '/byoda/public')
        self.assertEqual(data['restricted_bucket'], '/byoda/restricted')
        self.assertEqual(data['root_directory'], TEST_DIR)
        self.assertEqual(data['loglevel'], 'DEBUG')
        self.assertEqual(data['private_key_secret'], 'byoda')
        self.assertEqual(data['bootstrap'], True)
        self.assertTrue(len(data['services']))

        API = BASE_URL + '/v1/pod/member'
        resp = await ApiClient.call(
            f'{API}/service_id/{ADDRESSBOOK_SERVICE_ID}',
            method=HttpMethod.GET, timeout=120,
            headers=account_auth_header, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['account_id'], account_id)
        self.assertEqual(data['network'], 'byoda.net')
        self.assertTrue(isinstance(data['member_id'], str))
        self.assertEqual(data['service_id'], ADDRESSBOOK_SERVICE_ID)
        self.assertEqual(data['version'], ADDRESSBOOK_VERSION)
        self.assertEqual(data['name'], 'addressbook')
        self.assertEqual(data['owner'], 'Steven Hessing')
        self.assertEqual(data['website'], 'https://addressbook.byoda.org/')
        self.assertEqual(data['supportemail'], 'steven@byoda.org')
        self.assertEqual(
            data['description'], 'A simple network to maintain contacts'
        )
        self.assertGreater(len(data['certificate']), 80)
        self.assertGreater(len(data['private_key']), 80)

        with self.assertRaises(ByodaRuntimeError):
            resp = await ApiClient.call(
                f'{BASE_URL}/v1/pod/member/service_id/{ADDRESSBOOK_SERVICE_ID}'
                f'/version/{ADDRESSBOOK_VERSION}',
                method=HttpMethod.POST, timeout=120,
                headers=account_auth_header, app=APP
            )
            self.assertEqual(resp.status_code, 409)

        asset_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        API = (
            BASE_URL +
            f'/v1/pod/member/upload/service_id/{ADDRESSBOOK_SERVICE_ID}' +
            f'/asset_id/{asset_id}/visibility/public'
        )

        files: list[str, tuple(str, os.BufferedReader)] = [
            (
                'files', ('ls.bin', open('/bin/ls', 'rb'))
            ),
            (
                'files', ('date.bin', open('/bin/date', 'rb'))
            )
        ]

        resp = await ApiClient.call(
            API, method=HttpMethod.POST, files=files, timeout=120,
            headers=member_auth_header, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        expected_locations: list[str] = [
            f'{TEST_DIR}/public/{asset_id}/ls.bin',
            f'{TEST_DIR}/public/{asset_id}/date.bin',
        ]
        for location in data['locations']:
            self.assertTrue(location in expected_locations)
            self.assertTrue(os.path.exists(location))

        asset_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        API = (
            BASE_URL +
            f'/v1/pod/member/upload/service_id/{ADDRESSBOOK_SERVICE_ID}' +
            f'/asset_id/{asset_id}/visibility/restricted'
        )

        resp = await ApiClient.call(
            API, method=HttpMethod.POST, files=files,
            timeout=120, headers=member_auth_header, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        expected_locations = [
            f'{TEST_DIR}/restricted/{asset_id}/ls.bin',
            f'{TEST_DIR}/restricted/{asset_id}/date.bin',
        ]
        for location in data['locations']:
            self.assertTrue(location in expected_locations)
            self.assertTrue(os.path.exists(location))

    async def test_auth_token_request(self) -> None:
        account: Account = config.server.account
        password: str = os.environ['ACCOUNT_SECRET']

        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        class_name: str = 'network_links'

        #
        # First we get an account JWT
        #
        resp: HttpResponse = await ApiClient.call(
            f'{BASE_URL}/v1/pod/authtoken',
            method=HttpMethod.POST,
            data={
                'username': str(account.account_id)[:8],
                'password': password,
                'target_type': IdType.ACCOUNT.value,
            },
            headers={'Content-Type': 'application/json'},
            app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data: dict[str, str] = resp.json()
        account_jwt: str = data.get('auth_token')
        self.assertTrue(isinstance(account_jwt, str))
        auth_header: dict[str, str] = {
            'Authorization': f'bearer {account_jwt}'
        }

        #
        # Now we'll get a member JWT by using the account JWT and
        # the Data API call will fail while Data API call with
        # member JWT will succeed
        #
        resp = await ApiClient.call(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{service_id}',
            method=HttpMethod.POST, headers=auth_header, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        member_jwt = data.get('auth_token')
        self.assertTrue(isinstance(data.get("auth_token"), str))

        with self.assertRaises(ByodaRuntimeError):
            resp = await DataApiClient.call(
                service_id, class_name, DataRequestType.QUERY,
                headers={'Authorization': f'bearer {account_jwt}'}, app=APP
            )

        resp = await DataApiClient.call(
            service_id, class_name, DataRequestType.QUERY,
            headers={'Authorization': f'bearer {member_jwt}'}, app=APP
        )

        #
        # and then we get a member JWT using username/password
        #
        resp = await ApiClient.call(
            f'{BASE_URL}/v1/pod/authtoken',
            method=HttpMethod.POST,
            data={
                'username': str(member.member_id)[:8],
                'password': password,
                'service_id': ADDRESSBOOK_SERVICE_ID,
                'target_type': IdType.MEMBER.value,
            },
            app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        member_jwt: str | None = data.get('auth_token')
        self.assertTrue(isinstance(member_jwt, str))

        # Append some data
        network_link_data: dict[str, str] = {
            'data': {
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                ),
                'member_id': get_test_uuid(),
                'relation': 'friend',
            }
        }

        resp = await DataApiClient.call(
            service_id, class_name, DataRequestType.APPEND,
            headers={'Authorization': f'bearer {member_jwt}'},
            data=network_link_data, app=APP
        )
        self.assertEqual(resp.status_code, 200)

        # Read the data back
        resp = await DataApiClient.call(
            service_id, class_name, DataRequestType.QUERY,
            headers={'Authorization': f'bearer {member_jwt}'},
            app=APP
        )
        self.assertEqual(resp.status_code, 200)

        # and then we get a service JWT using username/password
        resp = await ApiClient.call(
            f'{BASE_URL}/v1/pod/authtoken',
            method=HttpMethod.POST,
            data={
                'username': str(member.member_id)[:8],
                'password': password,
                'service_id': service_id,
                'target_type': IdType.SERVICE.value,
            },
            app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        service_jwt = data.get('auth_token')
        self.assertTrue(isinstance(account_jwt, str))

        with self.assertRaises(ByodaRuntimeError):
            resp = await DataApiClient.call(
                service_id, class_name, DataRequestType.QUERY,
                headers={'Authorization': f'bearer {service_jwt}'},
                app=APP
            )
            self.assertEqual(resp.status_code, 403)

        # and then we get a app JWT using username/password
        resp = await ApiClient.call(
            f'{BASE_URL}/v1/pod/authtoken',
            method=HttpMethod.POST,
            data={
                'username': str(member.member_id)[:8],
                'password': password,
                'service_id': ADDRESSBOOK_SERVICE_ID,
                'target_type': IdType.APP.value,
                'app_id': str(get_test_uuid())
            },
            app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        app_jwt = data.get('auth_token')
        self.assertTrue(isinstance(account_jwt, str))

        with self.assertRaises(ByodaRuntimeError):
            resp = await DataApiClient.call(
                service_id, class_name, DataRequestType.QUERY,
                headers={'Authorization': f'bearer {app_jwt}'},
                app=APP
            )
            self.assertEqual(resp.status_code, 403)

        # Test failure cases
        with self.assertRaises(ByodaRuntimeError):
            resp = await ApiClient.call(
                f'{BASE_URL}/v1/pod/authtoken',
                method=HttpMethod.POST,
                data={
                    'username': '',
                    'password': '',
                    'target_type': IdType.ACCOUNT.value,
                },
                app=APP
            )
            self.assertEqual(resp.status_code, 401)
            data = resp.json()
            self.assertTrue('auth_token' not in data)

        with self.assertRaises(ByodaRuntimeError):
            resp = await ApiClient.call(
                f'{BASE_URL}/v1/pod/authtoken',
                method=HttpMethod.POST,
                data={
                    'username': 'wrong',
                    'password': os.environ['ACCOUNT_SECRET'],
                    'service_id': ADDRESSBOOK_SERVICE_ID,
                    'target_type': IdType.MEMBER.value,
                },
                app=APP
            )
            self.assertEqual(resp.status_code, 401)
            data = resp.json()
            self.assertTrue('auth_token' not in data)

        with self.assertRaises(ByodaRuntimeError):
            resp = await ApiClient.call(
                f'{BASE_URL}/v1/pod/authtoken',
                method=HttpMethod.POST,
                data={
                    'username': str(member.member_id)[:8],
                    'password': 'wrong',
                    'service_id': ADDRESSBOOK_SERVICE_ID,
                    'target_type': IdType.MEMBER.value,
                },
                app=APP
            )
            self.assertEqual(resp.status_code, 401)
            data = resp.json()
            self.assertTrue('auth_token' not in data)

        with self.assertRaises(ByodaRuntimeError):
            resp = await ApiClient.call(
                f'{BASE_URL}/v1/pod/authtoken',
                method=HttpMethod.POST,
                data={
                    'username': 'wrong',
                    'password': 'wrong',
                    'service_id': ADDRESSBOOK_SERVICE_ID,
                    'target_type': IdType.MEMBER.value,

                },
                app=APP
            )
            data = resp.json()
            self.assertEqual(resp.status_code, 401)
            self.assertTrue('auth_token' not in data)

        with self.assertRaises(ByodaRuntimeError):
            resp = await ApiClient.call(
                f'{BASE_URL}/v1/pod/authtoken',
                method=HttpMethod.POST,
                data={
                    'username': '',
                    'password': '',
                    'service_id': ADDRESSBOOK_SERVICE_ID,
                    'target_type': IdType.MEMBER.value,
                },
                app=APP
            )
            data = resp.json()
            self.assertEqual(resp.status_code, 401)
            self.assertTrue('auth_token' not in data)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
