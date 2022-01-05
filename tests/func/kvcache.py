#!/usr/bin/env python3

'''
Test the classes derived from KVCache

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import sys
import yaml
import unittest
from byoda.datacache.kv_cache import KVCache

from byoda.util.logger import Logger

from byoda.servers.service_server import ServiceServer

from byoda import config

CONFIG_FILE = 'tests/collateral/config.yml'


class TestKVCache(unittest.TestCase):
    PROCESS = None
    APP_CONFIG = None

    @classmethod
    def setUpClass(cls):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        with open(CONFIG_FILE) as file_desc:
            cls.APP_CONFIG = yaml.load(file_desc, Loader=yaml.SafeLoader)

        config.server = ServiceServer(cls.APP_CONFIG['cache'])

    @classmethod
    def tearDownClass(cls):
        pass

    def test_cache_ops(self):
        driver: KVCache = KVCache.create(TestKVCache.APP_CONFIG['cache'])

        self.assertFalse(driver.exists('test'))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
