#!/usr/bin/env python3

'''
Test cases for signatures for a service contract

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest
import logging

from byoda.datamodel.network import Network

from byoda.datamodel.schema import Schema

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from podserver.util import get_environment_vars

from byoda import config

from tests.lib import get_test_uuid


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

        shutil.copy('tests/collateral/addressbook.json', TEST_DIR)
        os.environ['ROOT_DIR'] = TEST_DIR
        os.environ['BUCKET_PREFIX'] = 'byoda'
        os.environ['CLOUD'] = 'LOCAL'
        os.environ['NETWORK'] = 'byoda.net'
        os.environ['ACCOUNT_ID'] = str(get_test_uuid())
        os.environ['ACCOUNT_SECRET'] = 'test'
        os.environ['LOGLEVEL'] = 'DEBUG'
        os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
        os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

        # Remaining environment variables used:
        network_data = get_environment_vars()

        network = Network(network_data, network_data)
        await network.load_network_secrets()
        config.server = PodServer()
        config.server.network = network

    @classmethod
    def tearDownClass(cls):
        # cls.PROCESS.terminate()
        pass

    # noqa: F841
    async def test_load_schema(self):
        uuid = get_test_uuid()                      # noqa: F841

        schema = await Schema.get_schema(
            'addressbook.json', config.server.network.paths.storage_driver,
            None, None, verify_contract_signatures=False
        )
        raise NotImplementedError('Need to complete this test case')


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
