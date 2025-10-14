'''
Test cases for Key/Value class using SQLite backend

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import os
import sys
import shutil

from uuid import uuid4
from logging import Logger

import unittest

from byoda.datatypes import CacheType
from byoda.datatypes import CacheTech

from byoda.datacache.kv_cache import KVCache
from byoda.util.logger import Logger as ByodaLogger

TEST_DIR = '/tmp/byoda-tests/kv_sqlite'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

    @classmethod
    async def asyncTearDown(self) -> None:
        pass

    async def test_cache(self):
        member_id = uuid4()
        cache: KVCache = await KVCache.create(
            f'{TEST_DIR}/test.db',  identifier=str(member_id),
            cache_tech=CacheTech.SQLITE,
            cache_type=CacheType.DATA
        )
        self.assertFalse(await cache.exists('blah'))
        self.assertIsNone(await cache.get('blah'))
        self.assertFalse(await cache.delete('blah'))

        self.assertTrue(await cache.set('blah', 'foo'))
        self.assertFalse(await cache.set('blah', 'foo'))
        self.assertTrue(await cache.exists('blah'))
        self.assertEqual(await cache.get('blah'), 'foo')

        self.assertTrue(await cache.delete('blah'))

        self.assertFalse(await cache.exists('blah'))
        self.assertIsNone(await cache.get('blah'))
        self.assertFalse(await cache.delete('blah'))

        await cache.close()


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )

    unittest.main()
