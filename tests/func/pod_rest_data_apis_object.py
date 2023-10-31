#!/usr/bin/env python3

'''
Test the POD REST and Data APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

# flake8: noqa: E266

import os
import sys
import unittest

from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.table import DataFilterSet

from byoda.datatypes import DataRequestType
from byoda.datatypes import AnyScalarType

from byoda.util.api_client.api_client import ApiClient

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda.servers.pod_server import PodServer

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter


from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars
from tests.lib.util import get_test_uuid

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.auth import get_member_auth_header
from tests.lib.util import call_data_api

# PodServer = TypeVar('PodServer')

# Settings must match config.yml used by directory server
NETWORK: str = config.DEFAULT_NETWORK

# This must match the test directory in tests/lib/testserver.p
TEST_DIR: str = '/tmp/byoda-tests/pod-rest-data-apis_object'

APP: FastAPI | None = None

ALL_DATA: list[dict[str, AnyScalarType]] = []


class TestRestDataApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=True)

        config.test_case = 'TEST_CLIENT'
        config.disable_pubsub = True

        server: PodServer = config.server

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

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
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_data_to_filter(self):
        server : PodServer = config.server
        account: Account = server.account
        member: Member = await account.get_membership(ADDRESSBOOK_SERVICE_ID)
        schema: Schema = member.schema
        object_data_class = schema.data_classes['asset']
        data = {
            'asset_id': 'aaaaaaaa-8fd6-4673-afa1-d3129e61faf3',
            'created_timestamp': '2023-10-29T05:15:39.495695+00:00',
            'asset_type': 'video'

        }
        delete_filter: DataFilterSet = DataFilterSet.from_data_class_data(
            object_data_class, data
        )

        delete_filter_str = str(delete_filter)
        comp_str: str = (
            "created_timestamp at '2023-10-29 05:15:39.495695+00:00' "
            "and asset_id eq 'aaaaaaaa-8fd6-4673-afa1-d3129e61faf3' "
            "and asset_type eq 'video'"
        )
        self.assertEqual(delete_filter_str, comp_str)
        self.assertTrue(isinstance(delete_filter, DataFilterSet))


    async def test_pod_rest_data_api_mutate_jwt(self):
        service_id: int = ADDRESSBOOK_SERVICE_ID

        member_auth_header = await get_member_auth_header(
            service_id=service_id, test=self, app=APP,
        )

        class_name = 'person'
        data = {
            'data': {
                'given_name': 'givenname',
                'family_name': 'familyname',
                'homepage_url': 'https://www.byoda.org',
                'email': 'steven@byoda.org',
                'avatar_url': 'https://dev.null',
            }
        }
        await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.MUTATE, data=data,
            auth_header=member_auth_header, app=APP,
        )

        result: dict[str, str] = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            auth_header=member_auth_header, app=APP,
        )
        result_data = result['edges'][0]['node']
        data['data']['additional_names'] = None
        self.assertEqual(data['data'], result_data)

    async def test_object_fields(self):
        service_id: int = ADDRESSBOOK_SERVICE_ID

        member_auth_header = await get_member_auth_header(
            service_id=service_id, test=self, app=APP,
        )

        class_name = 'person'
        data = {
            'data': {
                'given_name': 'givenname',
                'family_name': 'familyname',
                'homepage_url': 'https://www.byoda.org',
                'email': 'steven@byoda.org',
                'avatar_url': 'https://dev.null',
            }
        }
        await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.MUTATE, data=data,
            auth_header=member_auth_header, app=APP
        )

        fields: list[str] = ['given_name', 'family_name', 'homepage_url']
        result: dict[str, str] = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, fields=fields,
            auth_header=member_auth_header, app=APP
        )
        result_data = result['edges'][0]['node']

        # Requested fields
        self.assertIsNotNone(result_data['given_name'])
        self.assertIsNotNone(result_data['family_name'])
        self.assertIsNotNone(result_data['homepage_url'])

        # Not requested but required
        self.assertIsNotNone(result_data['email'])

        # Not requested nor required
        self.assertIsNone(result_data['avatar_url'])

    async def test_pod_rest_data_api_object_with_array(self):
        service_id: int = ADDRESSBOOK_SERVICE_ID

        member_auth_header = await get_member_auth_header(
            service_id=service_id, test=self, app=APP,
        )

        class_name: str = 'member'

        data = {
            'data': {
                'joined': str(datetime.now(tz=timezone.utc).isoformat()),
                'member_id': get_test_uuid(),
                'schema_versions': ["10", "5", "1"],
            }
        }
        resp: int = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.MUTATE, data=data,
            auth_header=member_auth_header, expect_success=False,
            app=APP
        )
        self.assertEqual(resp, 1)
        resp: dict[str, str] = await call_data_api(
            service_id, class_name, test=self, action=DataRequestType.QUERY,
            auth_header=member_auth_header, expect_success=False,
            app=APP
        )
        node = resp['edges'][0]['node']
        self.assertEqual(node['member_id'], str(data['data']['member_id']))
        self.assertEqual(
            node['schema_versions'], data['data']['schema_versions']
        )
        self.assertTrue(data['data']['joined'].startswith(node['joined'][:-1]))

        data['data']['schema_versions'] = ["10", "5", "1", "2"]
        resp: dict[str, str] = await call_data_api(
            service_id, class_name, test=self, action=DataRequestType.MUTATE,
            data=data, auth_header=member_auth_header, expect_success=False,
            app=APP
        )
        self.assertEqual(resp, 1)

        resp: dict[str, str] = await call_data_api(
            service_id, class_name, test=self, action=DataRequestType.QUERY,
            auth_header=member_auth_header, expect_success=False,
            app=APP
        )
        node = resp['edges'][0]['node']
        self.assertEqual(node['member_id'], str(data['data']['member_id']))
        self.assertEqual(
            node['schema_versions'], data['data']['schema_versions']
        )
        self.assertTrue(data['data']['joined'].startswith(node['joined'][:-1]))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
