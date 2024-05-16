#!/usr/bin/env python3

'''
Test cases for SchemaItem.normalize

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest

from uuid import UUID
from logging import getLogger
from datetime import datetime
from datetime import timezone

from byoda.datamodel.schema import Schema

from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.util.logger import Logger

from tests.lib.setup import setup_network

from byoda import config

from tests.lib.util import get_test_uuid


_LOGGER: Logger = getLogger(__name__)

NETWORK: str = config.DEFAULT_NETWORK

SCHEMA_PATH: str = os.environ.get(
    os.environ.get('LOCAL_SERVICE_CONTRACT')
)
if not SCHEMA_PATH:
    SCHEMA_PATH = 'tests/collateral/addressbook.json'

SCHEMA_FILE: str = os.path.basename(SCHEMA_PATH)

TEST_DIR: str = '/tmp/byoda-tests/pod-memberdata-normalize'
BASE_URL: str = 'http://localhost:{PORT}/api'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        shutil.copy(SCHEMA_PATH, TEST_DIR)
        os.environ['ROOT_DIR'] = TEST_DIR
        os.environ['PRIVATE_BUCKET'] = 'byoda'
        os.environ['RESTRICTED_BUCKET'] = 'byoda'
        os.environ['PUBLIC_BUCKET'] = 'byoda'
        os.environ['CLOUD'] = 'LOCAL'
        os.environ['NETWORK'] = 'byoda.net'
        os.environ['ACCOUNT_ID'] = str(get_test_uuid())
        os.environ['ACCOUNT_SECRET'] = 'test'
        os.environ['LOGLEVEL'] = 'DEBUG'
        os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
        os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

        await setup_network()

    @classmethod
    def tearDownClass(cls) -> None:
        pass

    # noqa: F841
    async def test_load_schema(self) -> None:
        uuid: UUID = get_test_uuid()
        now: datetime = datetime.now(timezone.utc)

        schema: Schema = await Schema.get_schema(
            SCHEMA_FILE, config.server.network.paths.storage_driver,
            None, None, verify_contract_signatures=False
        )
        data_classes: dict[str, object] = schema.get_data_classes()
        data: dict[str, any] = {
            'person': {
                'given_name': 'Steven',
                'family_name': 'Hessing',
                'email': 'steven@byoda.org'
            },
            MARKER_NETWORK_LINKS: [
                {
                    'created_timestamp': now.isoformat(),
                    'member_id': uuid,
                    'relation': 'follows'
                }
            ]
        }
        for field, value in data.items():
            if field not in data_classes:
                raise ValueError(
                    f'Found data field {field} not in the data classes '
                    'for the schema'
                )

            result = data_classes[field].normalize(value)
            data[field] = result

        self.assertTrue('person' in data)
        self.assertEqual(len(data['person']), 3)
        self.assertTrue(MARKER_NETWORK_LINKS in data)
        self.assertEqual(len(data[MARKER_NETWORK_LINKS]), 1)
        self.assertEqual(data[MARKER_NETWORK_LINKS][0]['relation'], 'follows')
        self.assertEqual(
            data[MARKER_NETWORK_LINKS][0]['created_timestamp'], now
        )
        self.assertEqual(data[MARKER_NETWORK_LINKS][0]['member_id'], uuid)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
