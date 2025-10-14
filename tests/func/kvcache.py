#!/usr/bin/env python3

'''
Test the classes derived from KVCache

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license
'''

import os
import sys
import yaml
import shutil
import unittest



from byoda.datamodel.network import Network

from byoda.servers.service_server import ServiceServer

from byoda.util.paths import Paths

from byoda import config

CONFIG_FILE = 'tests/collateral/config.yml'

TEST_KEY = 'test'


class TestKVCache(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self) -> None:
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

        network = Network(
            app_config['svcserver'], app_config['application']
        )
        network.paths = Paths(
            network=app_config['application']['network'],
            root_directory=test_dir
        )
        config.server = await ServiceServer.setup(network, app_config)

        # await network.load_network_secrets(storage_driver=local_storage)
        # await config.server.load_network_secrets()

        await config.server.member_db.kvcache.delete(TEST_KEY)

    @classmethod
    def tearDownClass(cls) -> None:
        pass

    async def test_cache_ops(self) -> None:
        driver = config.server.member_db.kvcache

        key = TEST_KEY
        self.assertFalse(await driver.exists(key))

        self.assertIsNone(await driver.get(key))

        self.assertTrue(await driver.set(key, 10))

        self.assertEqual(int(await driver.get(key)), 10)

        self.assertTrue(await driver.set(key, 10))

        self.assertTrue(await driver.set(key, 'just testing'))

        value = await driver.get(key)
        self.assertEqual(value.decode('utf-8'), 'just testing')

        self.assertTrue(await driver.set(key, {'test': 'result', 'sum': 3}))

        self.assertEqual(await driver.get(key), {'test': 'result', 'sum': 3})

        self.assertTrue(await driver.set(key, '{this is not json}'))

        self.assertEqual(await driver.get(key), b'{this is not json}')

        self.assertTrue(await driver.delete(key))

        self.assertFalse(await driver.delete(key))

        self.assertFalse(await driver.exists(key))

        self.assertTrue(await driver.push(key, 1))

        self.assertTrue(await driver.push(key, 2))

        self.assertEqual(await driver.pos(key, 2), 1)

        self.assertIsNone(await driver.pos(key, 3))

        self.assertEqual(await driver.pop(key), b'2')

        self.assertEqual(await driver.pop(key), b'1')

        self.assertIsNone(await driver.pop(key))

        self.assertTrue(await driver.push(key, 'a1'))
        self.assertTrue(await driver.push(key, 'b2'))
        self.assertTrue(await driver.push(key, 'c3'))

        self.assertEqual(await driver.shift_push_list(key), b'a1')

        self.assertEqual(await driver.get_list(key), [b'b2', b'c3', b'a1'])


if __name__ == '__main__':
    _LOGGER = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
