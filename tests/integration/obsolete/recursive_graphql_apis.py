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

from uuid import uuid4
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.graphql_proxy import GraphQlProxy

from byoda.util.message_signature import MessageSignature

from byoda.datatypes import IdType
from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.secrets.member_data_secret import MemberDataSecret

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

from tests.lib.defines import AZURE_POD_ACCOUNT_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from podserver.codegen.grapqhql_queries_4294929430 \
    import GRAPHQL_STATEMENTS as GRAPHQL_STMTS

from tests.lib.auth import get_azure_pod_jwt

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK
TIMEOUT: int = 900
TEST_DIR: str = '/tmp/byoda-tests/recursive-graphql'

APP: FastAPI | None = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    APP_CONFIG = None

    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=True)

        config.test_case = "TEST_CLIENT"
        config.disable_pubsub = True

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
            await member.enable_data_apis(APP, server.data_store, server.cache_store)

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

    @classmethod
    async def asyncTearDown(self):
        await GraphQlClient.close_all()

    async def test_graphql_addressbook_jwt(self):
        pod_account = config.server.account
        service_id = ADDRESSBOOK_SERVICE_ID
        account_member: Member = await pod_account.get_membership(service_id)

        resp = await ApiClient.call(
            f'{BASE_URL}/v1/pod/authtoken', HttpMethod.POST,
            data={
                'username': str(account_member.member_id)[:8],
                'password': os.environ['ACCOUNT_SECRET'],
                'service_id': ADDRESSBOOK_SERVICE_ID,
                'target_type': IdType.MEMBER.value,
            },
            app=APP
        )
        self.assertEqual(resp.status_code, 200)
        result = resp.json()

        auth_header = {
            'Authorization': f'bearer {result["auth_token"]}'
        }

        url = BASE_URL + f'/v1/data/service-{service_id}'

        class_name: str = 'network_assets'

        #
        # First query with depth = 1 shows only local results
        # because the remote pod has no entry in network_links with
        # relation 'friend' for us
        #
        vars = {
            'query_id': uuid4(),
            'depth': 1,
            'relations': ["friend"]
        }
        resp: HttpResponse = await GraphQlClient.call(
            url, GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=TIMEOUT, headers=auth_header, app=APP
        )
        result = resp.json()

        #
        # Now add the Azure pod as our friend
        #
        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        data = result['data'][field]['edges']
        self.assertEqual(len(data), 0)

        vars = {
            'member_id': AZURE_POD_MEMBER_ID,
            'relation': 'friend',
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            )
        }
        class_name = MARKER_NETWORK_LINKS

        resp: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
            vars=vars, timeout=TIMEOUT, headers=auth_header, app=APP
        )
        result = resp.json()

        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.APPEND
        )
        self.assertEqual(result['data'][field], 1)

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

        resp: HttpResponse = await GraphQlClient.call(
            azure_url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
            vars=vars, timeout=TIMEOUT, headers=azure_member_auth_header,
        )
        result = resp.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))

        # Confirm we have a network_link entry
        resp: HttpResponse = await GraphQlClient.call(
            azure_url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars={'query_id': uuid4()}, timeout=TIMEOUT,
            headers=azure_member_auth_header
        )
        result = resp.json()
        data = result.get('data')
        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        edges = data[field]['edges']
        self.assertGreaterEqual(len(edges), 1)
        filtered_edges = [
            edge for edge in edges
            if edge['network_link']['member_id'] == str(
                account_member.member_id
            )
        ]
        self.assertIsNotNone(filtered_edges)

        vars = {
            'query_id': uuid4(),
            'depth': 0,
        }
        class_name = 'network_assets'
        resp: HttpResponse = await GraphQlClient.call(
            azure_url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=TIMEOUT, headers=azure_member_auth_header
        )
        result = resp.json()
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

            resp: HttpResponse = await GraphQlClient.call(
                azure_url,
                GRAPHQL_STMTS[class_name][GraphQlRequestType.APPEND],
                vars=vars, timeout=TIMEOUT, headers=azure_member_auth_header
            )
            result = resp.json()
            data = result.get('data')
            self.assertIsNotNone(data)
            self.assertIsNone(result.get('errors'))

        vars = {
            'query_id': uuid4(),
            'depth': 0,
        }
        resp: HttpResponse = await GraphQlClient.call(
            azure_url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=TIMEOUT, headers=azure_member_auth_header
        )
        result = resp.json()

        data = result.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(result.get('errors'))
        edges = data[field]['edges']
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
        data_secret.private_key_file = 'azure-pod-member-data.key'
        with open('tests/collateral/local/azure-pod-private-key-password'
                  ) as file_desc:
            private_key_password = file_desc.read().strip()

        await data_secret.load(
            with_private_key=True, password=private_key_password
        )


        vars = {
            'query_id': uuid4(),
            'depth': depth,
            'relations': relations,
            'filters': filters,
            'timestamp': timestamp,
            'origin_member_id': origin_member_id,
            'origin_signature': origin_signature
        }

        class_name = 'network_assets'
        resp: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=TIMEOUT, headers=auth_header, app=APP
        )
        result = resp.json()

        self.assertIsNone(result.get('errors'))
        field = GraphQlClient.get_field_label(
            class_name, GraphQlRequestType.QUERY
        )
        data = result['data'][field]['edges']
        self.assertGreaterEqual(len(data), 3)

        #
        # Now we do the query for network assets to our pod with depth=1
        vars = {
            'query_id': uuid4(),
            'depth': 1,
            'relations': ["friend"]
        }
        resp: HttpResponse = await GraphQlClient.call(
            url,
            GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=TIMEOUT, headers=auth_header, app=APP
        )
        result = resp.json()

        self.assertIsNone(result.get('errors'))
        data = result['data'][field]['edges']
        self.assertGreaterEqual(len(data), 2)

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
            'query_id': uuid4(),
            'depth': depth,
            'relations': relations,
            'filters': filters,
            'timestamp': timestamp,
            'origin_member_id': origin_member_id,
            'origin_signature': origin_signature,
        }
        query = GRAPHQL_STMTS[class_name][GraphQlRequestType.QUERY]
        resp: HttpResponse = await GraphQlClient.call(
            url, query,
            vars=vars, timeout=TIMEOUT, headers=auth_header, app=APP
        )
        result = resp.json()

        self.assertIsNone(result.get('errors'))
        data = result['data'][field]['edges']
        self.assertGreaterEqual(len(data), 4)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
