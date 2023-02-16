#!/usr/bin/env python3

'''
Test the POD REST and GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

TODO: fix test case by connecting to the pod directly instead of via the
proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import unittest


from byoda.util.logger import Logger

from byoda.util.api_client.graphql_client import GraphQlClient

from tests.lib.setup import setup_network

from tests.lib.defines import AZURE_POD_ACCOUNT_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import AZURE_POD_SECRET_FILE
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS

from tests.lib.auth import get_jwt_header

TEST_DIR = '/tmp/byoda-tests/proxy_test'


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    async def test_graphql_addressbook_proxy(self):
        await setup_network(TEST_DIR)

        with open(AZURE_POD_SECRET_FILE) as file_desc:
            account_secret = file_desc.read().strip()

        id = AZURE_POD_MEMBER_ID

        service_id = ADDRESSBOOK_SERVICE_ID
        base_url = f'https://proxy.byoda.net/{service_id}/{id}/api'

        auth_header = get_jwt_header(
            base_url=base_url, id=id, secret=account_secret,
            member_token=True
        )
        self.assertIsNotNone(auth_header)

        url = base_url + f'/v1/data/service-{service_id}'
        response = await GraphQlClient.call(
            url, GRAPHQL_STATEMENTS['person']['query'], timeout=3,
            headers=auth_header
        )
        result = await response.json()
        self.assertIsNone(result.get('errors'))
        data = result.get('data')
        self.assertIsNotNone(data)

    async def test_account_jwt(self):
        await setup_network(TEST_DIR)

        with open(AZURE_POD_SECRET_FILE) as file_desc:
            account_secret = file_desc.read().strip()

        id = AZURE_POD_ACCOUNT_ID

        base_url = f'https://proxy.byoda.net/{id}/api'

        auth_header = get_jwt_header(
            base_url=base_url, id=id, secret=account_secret,
            member_token=False
        )

        self.assertIsNotNone(auth_header)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
