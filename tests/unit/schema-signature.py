#!/usr/bin/env python3

'''
Test cases for signatures for a service contract

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest
import logging

from byoda.datamodel.schema import Schema

from byoda.util.logger import Logger

from byoda import config

from tests.lib.util import get_test_uuid
from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network

_LOGGER = logging.getLogger(__name__)

NETWORK = config.DEFAULT_NETWORK
SCHEMA = 'tests/collateral/addressbook.json'

TEST_DIR = '/tmp/byoda-tests/pod-schema-signature'
BASE_URL = 'http://localhost:{PORT}/api'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        mock_environment_vars(TEST_DIR)
        await setup_network()

    @classmethod
    def tearDownClass(cls):
        # cls.PROCESS.terminate()
        pass

    # noqa: F841
    async def test_load_schema(self):
        uuid = get_test_uuid()                      # noqa: F841

        await Schema.get_schema(
            'addressbook.json', config.server.network.paths.storage_driver,
            None, None, verify_contract_signatures=False
        )
        # TODO: implement this test case
        raise NotImplementedError('Need to complete this test case')


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
