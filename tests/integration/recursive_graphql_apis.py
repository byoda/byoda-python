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
import shutil
import asyncio
import unittest
import requests

from datetime import datetime, timezone
from uuid import uuid4

from multiprocessing import Process
import uvicorn

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.util.message_signature import MessageSignature

from byoda.datamodel.graphql_proxy import GraphQlProxy

from byoda.secrets.member_data_secret import MemberDataSecret

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

from tests.lib.defines import AZURE_POD_ACCOUNT_ID
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

        shutil.copy(
            'tests/collateral/local/azure-pod-member-cert.pem',
            TEST_DIR
        )
        shutil.copy(
            'tests/collateral/local/azure-pod-member.key',
            TEST_DIR
        )
        shutil.copy(
            'tests/collateral/local/azure-pod-member-data-cert.pem',
            TEST_DIR
        )
        shutil.copy(
            'tests/collateral/local/azure-pod-member-data.key',
            TEST_DIR
        )

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

        url = BASE_URL + f'/v1/data/service-{service_id}'

        #
        # First query with depth = 1 shows only local results
        # because the remote pod has no entry in network_links with
        # relation 'friend' for us
        #
        vars = {
            'depth': 1,
            'relations': ["friend"]
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['query'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        #
        # Now add the Azure pod as our friend
        #
        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']
        self.assertEqual(len(data), 0)

        vars = {
            'member_id': AZURE_POD_MEMBER_ID,
            'relation': 'friend',
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            )
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_links']['append'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['append_network_links']
        self.assertEqual(len(data), 3)

        #
        # Add ourselves as a friend in the Azure pod
        #
        url = BASE_URL + f'/v1/data/service-{service_id}'

        azure_member_auth_header, azure_fqdn = await get_azure_pod_jwt(
            pod_account, TEST_DIR
        )
        azure_url = f'https://{azure_fqdn}/api/v1/data/service-{service_id}'

        vars = {
            'member_id': str(account_member.member_id),
            'relation': 'friend',
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            )
        }
        response = await GraphQlClient.call(
            azure_url, GRAPHQL_STATEMENTS['network_links']['append'],
            vars=vars, timeout=120, headers=azure_member_auth_header
        )
        result = await response.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        # Confirm we have a network_link entry
        response = await GraphQlClient.call(
            azure_url, GRAPHQL_STATEMENTS['network_links']['query'],
            timeout=120, headers=azure_member_auth_header
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
        self.assertIsNotNone(filtered_edges)

        vars = {
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
        # Here we generate a request as coming from the Azure pod
        # to the test pod to confirm the member data secret of the
        # Azure pod can be downloaded by the test pod to verify the
        # parameters of the request
        #
        azure_account = Account(
            AZURE_POD_ACCOUNT_ID, network=pod_account.network
        )
        azure_member = Member(
            ADDRESSBOOK_SERVICE_ID, azure_account
        )
        azure_member.member_id = AZURE_POD_MEMBER_ID

        data_secret = MemberDataSecret(
            azure_member.member_id, azure_member.service_id
        )

        data_secret.cert_file = 'azure-pod-member-data-cert.pem'
        data_secret.key_file = 'azure-pod-member-data.key'
        with open('tests/collateral/local/azure-pod-private-key-password'
                  ) as file_desc:
            private_key_password = file_desc.read().strip()

        await data_secret.load(
            with_private_key=True, password=private_key_password
        )

        plaintext = 'ik ben toch niet gek!'

        msg_sig = MessageSignature(data_secret)
        signature = msg_sig.sign_message(plaintext)
        msg_sig.verify_message(plaintext)
        signature = data_secret.sign_message(plaintext)
        data_secret.verify_message_signature(plaintext, signature)

        azure_member.schema = account_member.schema
        graphql_proxy = GraphQlProxy(azure_member)
        relations = ['friend']
        depth = 2
        filters = None
        timestamp = datetime.now(timezone.utc)
        origin_member_id = AZURE_POD_MEMBER_ID

        origin_signature = graphql_proxy.create_signature(
            ADDRESSBOOK_SERVICE_ID, relations, filters, timestamp,
            origin_member_id, member_data_secret=data_secret
        )

        await graphql_proxy.verify_signature(
            ADDRESSBOOK_SERVICE_ID, relations, filters, timestamp,
            origin_member_id, origin_signature
        )

        vars = {
            'depth': depth,
            'relations': relations,
            'filters': filters,
            'timestamp': timestamp,
            'origin_member_id': origin_member_id,
            'origin_signature': origin_signature
        }

        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['query'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']
        self.assertGreaterEqual(len(data), 3)

        #
        # Now we do the query for network assets to our pod with depth=1
        vars = {
            'depth': 1,
            'relations': ["friend"]
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['query'],
            vars=vars, timeout=120, headers=auth_header
        )
        result = await response.json()

        self.assertIsNone(result.get('errors'))
        data = result['data']['network_assets_connection']['edges']
        self.assertGreaterEqual(len(data), 3)

        #
        # Recursive query test
        #
        azure_account = Account(AZURE_POD_ACCOUNT_ID, pod_account.network)
        graphql_proxy = GraphQlProxy(account_member)
        relations = ['friend']
        depth = 2
        filters = None
        timestamp = datetime.now(timezone.utc)
        origin_member_id = str(account_member.member_id)
        origin_signature = graphql_proxy.create_signature(
            ADDRESSBOOK_SERVICE_ID, relations, filters, timestamp,
            origin_member_id
        )
        vars = {
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
        data = result['data']['network_links_connection']['edges']
        self.assertEqual(len(data), 1)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

unittest.main()
