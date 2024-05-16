#!/usr/bin/env python3

'''
Test the security of POD GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

import os
import sys
import unittest

from uuid import uuid4

from fastapi import FastAPI

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.graphql_client import GraphQlClient
from byoda.util.api_client.graphql_client import GraphQlRequestType

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

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from podserver.codegen.grapqhql_queries_4294929430 \
    import GRAPHQL_STATEMENTS

TEST_DIR = '/tmp/byoda-tests/graphql-apis-security'

APP: FastAPI | None = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
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
            await member.enable_data_apis(APP)

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
        class_name: str = 'person'
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS[class_name][GraphQlRequestType.QUERY],
            vars=vars, timeout=120, app=APP
        )
        result = response.json()

        self.assertIsNotNone(result.get('errors'))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
