#!/usr/bin/env python3

'''
Test the POD REST and GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import unittest

from uuid import uuid4
from datetime import datetime, timezone

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datacache.counter_cache import CounterCache

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

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

from tests.lib.auth import get_jwt_header

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

        for member in account.memberships.values():
            member.enable_graphql_api(app)

    @classmethod
    async def asyncTearDown(self):
        await GraphQlClient.close_all()

    async def test_graphql_counters(self):
        pod_account = config.server.account
        await pod_account.load_memberships()
        member: Member = pod_account.memberships.get(ADDRESSBOOK_SERVICE_ID)

        service_id = member.service_id

        auth_header = get_jwt_header(
            BASE_URL, member.member_id, service_id=service_id
        )

        url = BASE_URL + f'/v1/data/service-{service_id}'

        asset_ids: list[str] = []

        counter_cache: CounterCache = member.counter_cache
        start_counter = await counter_cache.get('network_assets')
        if not start_counter:
            start_counter = 0

        for count in range(1, 5):
            asset_id = uuid4()
            asset_ids.append(asset_id)
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

            cache_value = await counter_cache.get('network_assets')
            self.assertEqual(count, cache_value - start_counter)

        # Delete one asset
        vars = {
            'filters': {'asset_id': {'eq': str(asset_ids[0])}},
            'query_id': uuid4(),
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['delete'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNone(result.get('errors'))
        self.assertEqual(data['delete_from_network_assets'], 1)

        cache_value = await counter_cache.get('network_assets')
        self.assertEqual(cache_value, count + start_counter - 1)

        vars = {
            'filters': {'asset_id': {'eq': str(asset_ids[1])}},
            'query_id': uuid4(),
        }
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['network_assets']['delete'], vars=vars,
            timeout=120, headers=auth_header
        )
        result = await response.json()
        data = result.get('data')
        self.assertIsNone(result.get('errors'))
        self.assertEqual(data['delete_from_network_assets'], 1)

        cache_value = await counter_cache.get('network_assets')
        self.assertEqual(cache_value, count + start_counter - 2)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
