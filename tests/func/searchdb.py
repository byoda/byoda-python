#!/usr/bin/env python3

'''
Test the Search DB

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import sys
import yaml
import shutil
import unittest


from byoda.util.logger import Logger

from byoda.datamodel.network import Network

from byoda.datastore.searchdb import SearchDB, Tracker

from byoda.servers.service_server import ServiceServer

from byoda import config

from tests.lib.util import get_test_uuid


CONFIG_FILE = 'tests/collateral/config.yml'

TEST_MENTIONS = ['test', 'another']
TEST_HASHTAGS = ['#test', '#another']

TEST_DIR = '/tmp/byoda-tests/searchdb'


class TestSearchDB(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        with open(CONFIG_FILE) as file_desc:
            TestSearchDB.APP_CONFIG = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        app_config = TestSearchDB.APP_CONFIG

        test_dir = app_config['svcserver']['root_dir']
        try:
            shutil.rmtree(test_dir)
        except FileNotFoundError:
            pass

        os.makedirs(test_dir)

        # Create the network so that the constructor of ServiceServer
        # can load it.
        network: Network = await Network.create(
            app_config['application']['network'],
            app_config['svcserver']['root_dir'],
            app_config['svcserver']['private_key_password']
        )

        config.server = await ServiceServer.setup(network, app_config)

        search_db = config.server.search_db
        search_db.service_id = app_config['svcserver']['service_id']
        search_db.delete(TEST_MENTIONS[0], Tracker.MENTION)
        search_db.delete(TEST_MENTIONS[1], Tracker.MENTION)
        search_db.delete(TEST_HASHTAGS[0], Tracker.HASHTAG)
        search_db.delete(TEST_HASHTAGS[1], Tracker.HASHTAG)
        search_db.delete_counter(TEST_MENTIONS[0], Tracker.MENTION)
        search_db.delete_counter(TEST_MENTIONS[1], Tracker.MENTION)
        search_db.delete_counter(TEST_HASHTAGS[0], Tracker.HASHTAG)
        search_db.delete_counter(TEST_HASHTAGS[1], Tracker.HASHTAG)

    @classmethod
    def tearDownClass(cls):
        pass

    async def test_memberdb_ops(self):
        search_db: SearchDB = config.server.search_db

        self.assertFalse(
            await search_db.exists(TEST_MENTIONS[0], Tracker.MENTION)
        )
        self.assertFalse(
            await search_db.exists(TEST_MENTIONS[1], Tracker.MENTION)
        )
        self.assertFalse(
            await search_db.exists(TEST_HASHTAGS[0], Tracker.MENTION)
        )
        self.assertFalse(
            await search_db.exists(TEST_HASHTAGS[1], Tracker.MENTION)
        )

        member_id = get_test_uuid()
        asset_id = get_test_uuid()
        result = await search_db.create_append(
            TEST_MENTIONS[0], member_id, asset_id, Tracker.MENTION
        )

        results = await search_db.get_list(TEST_MENTIONS[0], Tracker.MENTION)
        self.assertEqual(len(results), 1)

        member_id = get_test_uuid()
        asset_id = get_test_uuid()
        result = await search_db.create_append(
            TEST_MENTIONS[0], member_id, asset_id, Tracker.MENTION
        )

        results = await search_db.get_list(TEST_MENTIONS[0], Tracker.MENTION)
        self.assertEqual(len(results), 2)

        member_id = get_test_uuid()
        asset_id = get_test_uuid()
        result = await search_db.create_append(
            TEST_MENTIONS[0], member_id, asset_id, Tracker.MENTION
        )

        self.assertEqual(result, 3)

        result = await search_db.erase_from_list(
            TEST_MENTIONS[0], member_id, asset_id, Tracker.MENTION
        )
        self.assertEqual(result, 2)

        results = await search_db.get_list(TEST_MENTIONS[0], Tracker.MENTION)
        self.assertEqual(len(results), 2)

        results = await search_db.delete(TEST_MENTIONS[0], Tracker.MENTION)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
