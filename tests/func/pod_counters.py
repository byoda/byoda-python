#!/usr/bin/env python3

'''
Test the POD Data REST APIs for counters

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license
'''

import os
import sys
import unittest

from uuid import uuid4
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datacache.counter_cache import CounterCache

from byoda.datatypes import DataRequestType
from byoda.datatypes import DATA_API_URL

from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.servers.pod_server import PodServer

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
from tests.lib.setup import get_account_id

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.auth import get_member_auth_header

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/podserver'

_LOGGER = None

POD_ACCOUNT: Account = None

APP: FastAPI | None = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)

        network_data = await setup_network(delete_tmp_dir=False)

        network_data['account_id'] = get_account_id(network_data)

        config.test_case = "TEST_CLIENT"

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

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

        server: PodServer = config.server
        for member in account.memberships.values():
            await member.create_query_cache()
            await member.create_counter_cache()
            await member.enable_data_apis(APP, server.data_store)

    @classmethod
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_rest_counters(self):
        account = config.server.account

        member: Member = await account.get_membership(
            ADDRESSBOOK_SERVICE_ID
        )

        service_id: int = member.service_id

        auth_header: dict[str, str] = await get_member_auth_header(
            service_id=service_id, app=None
        )

        class_name: str = 'network_assets'
        data_append_url: str = DATA_API_URL.format(
            protocol='http', fqdn='127.0.0.1', port=8000,
            service_id=service_id, class_name=class_name,
            action=DataRequestType.APPEND.value
        )

        asset_ids: list[str] = []

        counter_cache: CounterCache = member.counter_cache
        start_counter = await counter_cache.get(class_name)
        if not start_counter:
            start_counter = 0

        for count in range(1, 5):
            asset_id = uuid4()
            asset_ids.append(asset_id)
            vars = {
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                ),
                'asset_type': 'post',
                'asset_id': str(asset_id),
                'creator': f'test account #{count}',
                'title': 'test asset',
                'subject': 'just a test asset',
                'contents': 'some utf-8 markdown string',
                'keywords': ["just", "testing"]
            }
            class_name: str = 'network_assets'
            response: HttpResponse = await RestApiClient.call(
                data_append_url, HttpMethod.POST, data={'data': vars},
                timeout=120, headers=auth_header, app=None
            )
            result = response.json()
            self.assertEqual(result, 1)

            cache_value = await counter_cache.get(class_name)
            self.assertEqual(count, cache_value - start_counter)

        # Delete one asset
        data_delete_url: str = DATA_API_URL.format(
            protocol='http', fqdn='127.0.0.1', port=8000,
            service_id=service_id, class_name=class_name,
            action=DataRequestType.DELETE.value
        )
        vars = {
            'filter': {'asset_id': {'eq': str(asset_ids[0])}},
            'query_id': uuid4(),
        }
        response: HttpResponse = await RestApiClient.call(
            data_delete_url, HttpMethod.POST, data=vars,
            timeout=120, headers=auth_header, app=None
        )
        result = response.json()
        self.assertEqual(result, 1)

        cache_value = await counter_cache.get(class_name)
        self.assertEqual(cache_value, count + start_counter - 1)

        vars = {
            'filter': {'asset_id': {'eq': str(asset_ids[1])}},
            'query_id': uuid4(),
        }
        response: HttpResponse = await RestApiClient.call(
            data_delete_url, HttpMethod.POST, data=vars,
            timeout=120, headers=auth_header, app=None
        )
        result = response.json()
        self.assertEqual(result, 1)

        cache_value = await counter_cache.get(class_name)
        self.assertEqual(cache_value, count + start_counter - 2)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
