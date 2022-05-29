#!/usr/bin/env python3

'''
Test the Directory APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import os
import sys
import shutil
import asyncio
import unittest
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone
from uuid import UUID

from multiprocessing import Process
import fastapi
import uvicorn

from python_graphql_client import GraphqlClient

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.datastore.document_store import DocumentStoreType
from byoda.datatypes import CloudType
from byoda.datatypes import IdType

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from byoda.secrets.member_secret import MemberSecret
from byoda.requestauth.jwt import JWT

from byoda.servers.pod_server import PodServer

from podserver.util import get_environment_vars
from podserver.routers import account
from podserver.routers import member
from podserver.routers import authtoken

from tests.lib import get_test_uuid

from tests.lib.graphql_queries import QUERY_PERSON
from tests.lib.graphql_queries import MUTATE_PERSON
from tests.lib.graphql_queries import QUERY_NETWORK
from tests.lib.graphql_queries import QUERY_NETWORK_WITH_FILTER
from tests.lib.graphql_queries import APPEND_NETWORK
from tests.lib.graphql_queries import UPDATE_NETWORK_RELATION
from tests.lib.graphql_queries import DELETE_FROM_NETWORK_WITH_FILTER

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/pod_apis'
BASE_URL = 'http://localhost:{PORT}/api'

_LOGGER = None

POD_ACCOUNT: Account = None

ADDRESSBOOK_SERVICE_ID = None
ADDRESSBOOK_VERSION = 1

EVENTS = []


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        EVENTS.append('asyncSetUp')
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)
        shutil.copy('tests/collateral/addressbook.json', TEST_DIR)

        os.environ['ROOT_DIR'] = TEST_DIR
        os.environ['BUCKET_PREFIX'] = 'byoda'
        os.environ['CLOUD'] = 'LOCAL'
        os.environ['NETWORK'] = 'byoda.net'
        os.environ['ACCOUNT_ID'] = str(get_test_uuid())
        os.environ['ACCOUNT_SECRET'] = 'test'
        os.environ['LOGLEVEL'] = 'DEBUG'
        os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
        os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

        # Remaining environment variables used:
        network_data = get_environment_vars()

        network = Network(network_data, network_data)
        await network.load_network_secrets()

        config.test_case = True

        config.server = PodServer(network)
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType(network_data['cloud']),
            bucket_prefix=network_data['bucket_prefix'],
            root_dir=network_data['root_dir']
        )

        server.paths = network.paths

        pod_account = Account(network_data['account_id'], network)
        await pod_account.paths.create_account_directory()
        await pod_account.load_memberships()

        server.account = pod_account

        pod_account.password = os.environ['ACCOUNT_SECRET']

        await pod_account.create_account_secret()
        await pod_account.create_data_secret()
        await pod_account.register()

        await server.get_registered_services()

        service = [
            service
            for service in server.network.service_summaries.values()
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
                'log_level': 'debug'
            },
            daemon=True
        )
        TestDirectoryApis.PROCESS.start()
        await asyncio.sleep(2)

    @classmethod
    async def asyncTearDown(self):
        EVENTS.append('asyncSetUp')

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
        response = requests.get(API, headers=account_headers)
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
            headers=account_headers
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
            headers=account_headers
        )
        self.assertEqual(response.status_code, 409)

        response = requests.put(
            (
                f'{BASE_URL}/v1/pod/member/service_id/{service_id}'
                f'/version/{version}'
            ),
            headers=account_headers
        )
        self.assertEqual(response.status_code, 409)

    def test_pod_rest_api_jwt(self):

        account = config.server.account
        account_id = account.account_id

        #
        # This test fails because a member-JWT can't be used for REST APIs,
        # only for GraphQL APIs
        #
        response = requests.get(
            f'{BASE_URL}/v1/pod/authtoken/service_id/{ADDRESSBOOK_SERVICE_ID}',
            auth=HTTPBasicAuth(
                str(account_id)[:8], os.environ['ACCOUNT_SECRET']
            )
        )
        data = response.json()
        auth_header = {
            'Authorization': f'bearer {data["auth_token"]}'
        }

        API = BASE_URL + '/v1/pod/account'
        response = requests.get(API, headers=auth_header)
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
        auth_header = {
            'Authorization': f'bearer {data["auth_token"]}'
        }

        API = BASE_URL + '/v1/pod/account'
        response = requests.get(API, headers=auth_header)
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
            f'{API}/service_id/{ADDRESSBOOK_SERVICE_ID}', headers=auth_header
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
            headers=auth_header
        )
        self.assertEqual(response.status_code, 409)

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
        self.assertTrue(isinstance(data.get('auth_token'), str))

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
        data = response.json()
        auth_header = {
            'Authorization': f'bearer {data["auth_token"]}'
        }

        url = BASE_URL + f'/v1/data/service-{service_id}'
        client = GraphqlClient(endpoint=url)

        result = client.execute(
            query=MUTATE_PERSON.format(
                given_name='Peter',
                additional_names='',
                family_name='Hessing',
                email='steven@byoda.org',
                homepage_url='https://byoda.org',
                avatar_url='https://some.place/somewhere'

            ),
            headers=auth_header
        )
        self.assertTrue('data' in result)
        self.assertIsNotNone(result['data'])
        self.assertTrue('mutate_person' in result['data'])
        self.assertEqual(
            result['data']['mutate_person']['given_name'], 'Peter'
        )

        with self.assertRaises(KeyError) as context:
            result = client.execute(
                query=MUTATE_PERSON.format(
                    family_name='Hessing',
                    homepage_url='https://byoda.net'
                ),
                headers=auth_header
            )

        self.assertTrue('given_name' in context.exception.args)

        #
        # JWT for the 'Azure POD' member
        #

        # add network_link for the 'remote member'
        remote_member_id = '0c8143d8-9311-485d-a639-ed8ef980bebb'
        result = client.execute(
            APPEND_NETWORK.format(
                uuid=remote_member_id,
                relation='friend',
                timestamp=str(datetime.now(tz=timezone.utc).isoformat())
            ),
            headers=auth_header
        )
        self.assertIsNotNone(result['data'])
        self.assertIsNone(result.get('errors'))
        member_dir = account.paths.member_directory(ADDRESSBOOK_SERVICE_ID)
        dest_dir = f'{TEST_DIR}/{member_dir}'

        shutil.copy(
            'tests/collateral/local/azure-pod-member-cert.pem',
            dest_dir
        )
        shutil.copy(
            'tests/collateral/local/azure-pod-member.key',
            dest_dir
        )

        secret = MemberSecret(
            remote_member_id, ADDRESSBOOK_SERVICE_ID, account
        )
        secret.cert_file = f'{member_dir}/azure-pod-member-cert.pem'
        secret.private_key_file = f'{member_dir}/azure-pod-member.key'
        await secret.load()
        jwt = JWT.create(
            remote_member_id, IdType.MEMBER, secret, account.network.name,
            service_id=ADDRESSBOOK_SERVICE_ID
        )
        remote_member_auth_header = {
            'Authorization': f'bearer {jwt.encoded}'
        }

        result = client.execute(
            query=QUERY_PERSON, headers=remote_member_auth_header
        )

        self.assertTrue('data' in result)
        self.assertIsNotNone(result['data'])

        result = client.execute(
            DELETE_FROM_NETWORK_WITH_FILTER.format(
                field='member_id', cmp='eq', value=remote_member_id
            ),
            headers=auth_header
        )
        self.assertIsNotNone(result['data'])
        self.assertEqual(len(result['data']['delete_from_network_links']), 1)
        self.assertEqual(
            result['data']['delete_from_network_links'][0]['relation'],
            'friend'
        )

        result = client.execute(
            APPEND_NETWORK.format(
                uuid=remote_member_id,
                relation='colleague',
                timestamp=str(datetime.now(tz=timezone.utc).isoformat())
            ),
            headers=auth_header
        )
        self.assertIsNotNone(result['data'])
        self.assertIsNone(result.get('errors'))

        result = client.execute(
            query=QUERY_PERSON, headers=remote_member_auth_header
        )

        self.assertIsNone(result['data'])
        self.assertTrue(result['errors'])

    def test_graphql_addressbook_tls_cert(self):
        account = config.server.account
        account_id = account.account_id
        network = account.network

        service_id = ADDRESSBOOK_SERVICE_ID

        account_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={account_id}.accounts.{network.name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.name}'
        }

        API = BASE_URL + '/v1/pod/member'
        response = requests.get(
            API + f'/service_id/{service_id}', headers=account_headers
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

        url = f'{BASE_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'
        client = GraphqlClient(endpoint=url)

        result = client.execute(
            query=MUTATE_PERSON.format(
                given_name='Carl',
                additional_names='',
                family_name='Hessing',
                email='steven@byoda.org',
                homepage_url='https://byoda.org',
                avatar_url='https://some.place/somewhere'
            ),
            headers=member_headers)
        self.assertEqual(
            result['data']['mutate_person']['given_name'], 'Carl'
        )

        result = client.execute(query=QUERY_PERSON, headers=member_headers)

        result = client.execute(
            query=MUTATE_PERSON.format(
                given_name='Steven',
                additional_names='',
                family_name='Hessing',
                email='steven@byoda.org',
                homepage_url='https://byoda.org',
                avatar_url='https://some.place/somewhere'
            ),
            headers=member_headers
        )
        self.assertEqual(
            result['data']['mutate_person']['given_name'], 'Steven'
        )

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
        result = client.execute(query, headers=member_headers)
        self.assertIsNone(result['data'])
        self.assertIsNotNone(result['errors'])

        # Test with cert of another member
        alt_member_id = get_test_uuid()

        alt_member_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={alt_member_id}.members-0.{NETWORK}',
            'X-Client-SSL-Issuing-CA': f'CN=members-ca.{NETWORK}'
        }

        # Query fails because other members do not have access
        result = client.execute(QUERY_PERSON, headers=alt_member_headers)
        self.assertIsNone(result['data'])
        self.assertIsNotNone(result['errors'])

        result = client.execute(
            APPEND_NETWORK.format(
                uuid=get_test_uuid(),
                relation='follow',
                timestamp=str(datetime.now(tz=timezone.utc).isoformat())
            ),
            headers=member_headers
        )
        self.assertIsNotNone(result['data'])
        self.assertIsNone(result.get('errors'))

        result = client.execute(
            APPEND_NETWORK.format(
                uuid=get_test_uuid(),
                relation='follow',
                timestamp=str(datetime.now(tz=timezone.utc).isoformat())
            ),
            headers=member_headers
        )
        self.assertIsNotNone(result['data'])
        self.assertIsNone(result.get('errors'))

        friend_uuid = get_test_uuid()
        friend_timestamp = str(datetime.now(tz=timezone.utc).isoformat())
        result = client.execute(
            APPEND_NETWORK.format(
                uuid=friend_uuid,
                relation='friend',
                timestamp=friend_timestamp
            ),
            headers=member_headers
        )
        self.assertIsNotNone(result['data'])
        self.assertIsNone(result.get('errors'))

        result = client.execute(
            QUERY_NETWORK,
            headers=member_headers
        )
        self.assertIsNotNone(result['data'])
        self.assertNotEqual(
            result['data']['network_links'][0],
            result['data']['network_links'][1]
        )
        self.assertNotEqual(
            result['data']['network_links'][1],
            result['data']['network_links'][2]
        )

        result = client.execute(
            QUERY_NETWORK_WITH_FILTER.format(
                field='relation', cmp='eq', value='friend'
            ),
            headers=member_headers
        )
        self.assertIsNotNone(result['data'])
        self.assertEqual(len(result['data']['network_links']), 1)

        result = client.execute(
            QUERY_NETWORK_WITH_FILTER.format(
                field='relation', cmp='eq', value='follow'
            ),
            headers=member_headers
        )

        self.assertNotEqual(
            result['data']['network_links'][0],
            result['data']['network_links'][1]
        )

        result = client.execute(
            QUERY_NETWORK_WITH_FILTER.format(
                field='timestamp', cmp='at', value=friend_timestamp
            ),
            headers=member_headers
        )
        self.assertIsNotNone(result['data'])
        self.assertEqual(len(result['data']['network_links']), 1)
        self.assertEqual(
            result['data']['network_links'][0]['relation'], 'friend'
        )

        result = client.execute(
            UPDATE_NETWORK_RELATION.format(
                field='member_id', cmp='eq', value=friend_uuid,
                relation='best_friend'
            ),
            headers=member_headers
        )
        self.assertIsNotNone(result['data'])
        self.assertEqual(
            result['data']['update_network_links']['relation'],
            'best_friend'
        )
        self.assertEqual(
            result['data']['update_network_links']['member_id'],
            str(friend_uuid)
        )

        result = client.execute(
            DELETE_FROM_NETWORK_WITH_FILTER.format(
                field='timestamp', cmp='at', value=friend_timestamp
            ),
            headers=member_headers
        )
        self.assertIsNotNone(result['data'])
        self.assertEqual(len(result['data']['delete_from_network_links']), 1)
        self.assertEqual(
            result['data']['delete_from_network_links'][0]['relation'],
            'best_friend'
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
    print(', '.join(EVENTS))
