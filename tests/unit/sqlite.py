'''
Test cases for Sqlite storage

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest
from datetime import datetime, timezone

from byoda.datamodel.schema import Schema
from byoda.datamodel.network import Network
from byoda.servers.pod_server import PodServer

from byoda import config

from podserver.util import get_environment_vars

from byoda.util.logger import Logger

from tests.lib.util import get_test_uuid

NETWORK = config.DEFAULT_NETWORK
SCHEMA = 'tests/collateral/addressbook.json'

TEST_DIR = '/tmp/byoda-tests/pod-schema-signature'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        shutil.copy(SCHEMA, TEST_DIR)
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

    async def test_schema(self):
        schema = await Schema.get_schema(
            'addressbook.json', config.server.network.paths.storage_driver,
            None, None, verify_contract_signatures=False
        )
        schema.get_graphql_classes()

        uuid = get_test_uuid()
        now = datetime.now(timezone.utc)
        data = {
            'person': {
                'given_name': 'Steven',
                'family_name': 'Hessing',
                'email': 'steven@byoda.org'
            },
            'network_links': [
                {
                    'timestamp': now.isoformat(),
                    'member_id': uuid,
                    'relation': 'follows'
                }
            ]
        }
        self.assertIsNotNone(schema)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
