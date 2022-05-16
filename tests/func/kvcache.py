#!/usr/bin/env python3

'''
Test the classes derived from KVCache

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import os
import sys
import yaml
import shutil
import unittest

from byoda.util.logger import Logger

from byoda.datamodel.network import Network

from byoda.servers.service_server import ServiceServer

from byoda import config

CONFIG_FILE = 'tests/collateral/config.yml'

TEST_KEY = 'test'


class TestKVCache(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        with open(CONFIG_FILE) as file_desc:
            TestKVCache.APP_CONFIG = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        app_config = TestKVCache.APP_CONFIG

        test_dir = app_config['svcserver']['root_dir']
        try:
            shutil.rmtree(test_dir)
        except FileNotFoundError:
            pass

        os.makedirs(test_dir)

        network = await Network.create(
            app_config['application']['network'],
            app_config['svcserver']['root_dir'],
            app_config['svcserver']['private_key_password']
        )
        await network.load_network_secrets()

        config.server = ServiceServer(app_config)
        await config.server.load_network_secrets()

        config.server.member_db.kvcache.delete(TEST_KEY)

    @classmethod
    def tearDownClass(cls):
        pass

    def test_cache_ops(self):
        driver = config.server.member_db.kvcache

        key = TEST_KEY
        self.assertFalse(driver.exists(key))

        self.assertIsNone(driver.get(key))

        self.assertTrue(driver.set(key, 10))

        self.assertEqual(int(driver.get(key)), 10)

        self.assertTrue(driver.set(key, 10))

        self.assertTrue(driver.set(key, 'just testing'))

        self.assertEqual(driver.get(key).decode('utf-8'), 'just testing')

        self.assertTrue(driver.set(key, {'test': 'result', 'sum': 3}))

        self.assertEqual(driver.get(key), {'test': 'result', 'sum': 3})

        self.assertTrue(driver.set(key, '{this is not json}'))

        self.assertEqual(driver.get(key), b'{this is not json}')

        self.assertTrue(driver.delete(key))

        self.assertFalse(driver.delete(key))

        self.assertFalse(driver.exists(key))

        self.assertTrue(driver.push(key, 1))

        self.assertTrue(driver.push(key, 2))

        self.assertEqual(driver.pos(key, 2), 1)

        self.assertIsNone(driver.pos(key, 3))

        self.assertEqual(driver.pop(key), b'2')

        self.assertEqual(driver.pop(key), b'1')

        self.assertIsNone(driver.pop(key))

        self.assertTrue(driver.push(key, 'a1'))
        self.assertTrue(driver.push(key, 'b2'))
        self.assertTrue(driver.push(key, 'c3'))

        self.assertEqual(driver.shift_push_list(key), b'a1')

        self.assertEqual(driver.get_list(key), [b'b2', b'c3', b'a1'])


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
