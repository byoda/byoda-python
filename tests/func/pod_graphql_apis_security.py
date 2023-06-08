#!/usr/bin/env python3

'''
Test the security of POD GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import unittest
import requests

from uuid import UUID, uuid4
from datetime import datetime, timezone

from byoda.datamodel.account import Account
from byoda.datamodel.network import Network

from byoda.datatypes import MARKER_NETWORK_LINKS

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
from tests.lib.util import get_test_uuid
from tests.lib.setup import get_account_id

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/podserver'

_LOGGER = None

POD_ACCOUNT: Account = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
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

        for account_member in account.memberships.values():
            account_member.enable_graphql_api(app)

    @classmethod
    async def asyncTearDown(self):
        await GraphQlClient.close_all()

    async def test_graphql_addressbook_tls_cert(self):
        url = f'{BASE_URL}/v1/data/service-{ADDRESSBOOK_SERVICE_ID}'

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
            url, GRAPHQL_STATEMENTS['person']['query'],
            vars=vars, timeout=120
        )
        result = await response.json()

        self.assertIsNotNone(result.get('errors'))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
