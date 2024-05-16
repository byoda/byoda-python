#!/usr/bin/env python3

'''
Test the POD REST and Data APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

TODO: fix test case by connecting to the pod directly instead of via the
proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

import sys
import unittest

from byoda.util.logger import Logger

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network

from tests.lib.defines import AZURE_POD_ACCOUNT_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import AZURE_POD_ACCOUNT_SECRET_FILE
from tests.lib.defines import AZURE_POD_MEMBER_SECRET_FILE
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.auth import get_jwt_header

TEST_DIR = '/tmp/byoda-tests/proxy_test'


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    async def test_data_api_addressbook_proxy(self):
        # DataApiClient needs member.schema.get_data_classes() and
        # data_store.setup_member_db()
        raise NotImplementedError(
            'Needs to be refactored to use DataApiClient'
        )
        mock_environment_vars(TEST_DIR)
        await setup_network(TEST_DIR)

        with open(AZURE_POD_ACCOUNT_SECRET_FILE) as file_desc:
            account_secret = file_desc.read().strip()

        id = AZURE_POD_ACCOUNT_ID

        base_url = f'https://proxy.byoda.net/{id}/api'

        auth_header = get_jwt_header(
            base_url=base_url, id=id,
            secret=account_secret, service_id=None
        )

        self.assertIsNotNone(auth_header)

        id = AZURE_POD_MEMBER_ID
        service_id = ADDRESSBOOK_SERVICE_ID
        base_url = f'https://proxy.byoda.net/{service_id}/{id}/api'

        with open(AZURE_POD_MEMBER_SECRET_FILE) as file_desc:
            account_secret = file_desc.read().strip()

        auth_header = get_jwt_header(
            base_url=base_url, id=id,
            secret=account_secret, service_id=service_id
        )
        self.assertIsNotNone(auth_header)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
