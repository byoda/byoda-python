'''
Test the LUA script for getting the data of a list of assets

This test requires:
- installation of the redis-tools package with the 'redis-cli' command
- a running Redis server at '192.168.1.11:6379' without a
  password. Alternatively, a Redis server can be specified with the
  REDIS_URL environment variable.

This test will delete in the Redis server:
- all keys under 'testlualist*'
- all keys under 'assets*'
- all Redis (lua) functions
- the Redis search index asset_index

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license
'''

import os
import sys
import unittest

import subprocess

import orjson

from uuid import UUID
from uuid import uuid4
from datetime import datetime
from datetime import timedelta
from datetime import UTC

from byoda.datacache.searchable_cache import KEY_PREFIX
from byoda.datacache.searchable_cache import SearchableCache
from byoda.datacache.asset_cache import AssetNode
from byoda.util.logger import Logger

LUA_SCRIPT_FILEPATH: str = 'tests/collateral/test_redis_lua.lua'

REDIS_URL: str = os.getenv('REDIS_URL', 'redis://192.168.1.11:6379')

TESTLIST: str = 'testlualist'


class TestRedisLuaScript(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def asyncSetUp() -> None:
        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)

        await cache.client.function_flush('SYNC')
        await cache.client.ft(cache.index_name).dropindex()
        list_key: str = cache.get_list_key(TESTLIST)
        keys: list[str] = await cache.client.keys(f'{list_key}*')
        for key in keys:
            await cache.client.delete(key)

        keys: list[str] = await cache.client.keys(f'{KEY_PREFIX}*')
        for key in keys:
            await cache.client.delete(key)

        await cache.client.aclose()

    @staticmethod
    async def asyncTearDown() -> None:
        pass

    async def test_lua_get_list_values(self) -> None:
        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)
        self.assertIsNotNone(cache)

        member_id: UUID = uuid4()

        assets: list[dict[str, str | dict[str, any]]] = await populate_cache(
            cache, TESTLIST, member_id
        )

        data: list[dict[str, any]]
        # Run without 'first' or 'after' argument
        data = call_lua_script(self)
        self.assertEqual(len(data), 20)

        data = call_lua_script(self, 10)
        self.assertEqual(len(data), 10)

        data = call_lua_script(self, 30)
        self.assertEqual(len(data), 20)

        data = call_lua_script(self, 12, assets[15]['cursor'])
        self.assertEqual(len(data), 12)

        data = call_lua_script(self, 20, assets[15]['cursor'])
        self.assertEqual(len(data), 15)

        data = call_lua_script(self, 20, 'notacursor')
        self.assertEqual(len(data), 20)

        await cache.close()

    async def test_search(self) -> None:
        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)

        member_id: UUID = uuid4()

        assets: list[dict[str, str | dict[str, any]]] = await populate_cache(
            cache, TESTLIST, member_id
        )
        result = await cache.client.ft(cache.index_name).search('Fight')
        self.assertEqual(result['total_results'.encode('utf-8')], 1)
        self.assertEqual(len(result['results'.encode('utf-8')]), 1)

    async def test_pagination(self) -> None:
        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)

        member_id: UUID = uuid4()

        assets: list[dict[str, str | dict[str, any]]] = await populate_cache(
            cache, TESTLIST, member_id
        )

        data: list
        data = await cache.get_list_values(TESTLIST, KEY_PREFIX)
        self.assertEqual(len(data), 20)

        data = await cache.get_list_values(
            TESTLIST, KEY_PREFIX, after=assets[5]['cursor'], first=5
        )
        self.assertEqual(len(data), 5)

        data = await cache.get_list_values(
            TESTLIST, KEY_PREFIX, after=assets[5]['cursor'], first=10
        )
        self.assertEqual(len(data), 5)

        data = await cache.get_list_values(
            TESTLIST, KEY_PREFIX, after=assets[15]['cursor']
        )
        self.assertEqual(len(data), 15)

        await cache.close()


def call_lua_script(test, first: int | None = None, after: str | None = None
                    ) -> list[dict[str, any]]:
    if after and not first:
        raise ValueError('Cannot specify "after" without "first"')

    cmd: list[str] = [
        'redis-cli', '-3', '-u', REDIS_URL,
        '--eval', LUA_SCRIPT_FILEPATH,
        f'lists:{TESTLIST}', ',', 'assets'
    ]
    if first or after:
        # The comma in the parameters to 'redis-cli' separate the 'KEYS'
        # from the 'ARGV' arguments, see:
        # https://redis.io/docs/interact/programmability/lua-debugging/
        cmd.append(f'{first}')
        if after:
            cmd.append(f'{after}')

    result: subprocess.CompletedProcess = subprocess.run(
        cmd, capture_output=True,
    )

    test.assertTrue(result.returncode == 0)
    data: list[dict[str, any]] = []
    for line in result.stdout.splitlines():
        data.append(orjson.loads(line))

    return data


async def populate_cache(cache: SearchableCache, asset_list: str,
                         member_id: UUID) -> list[dict]:
    titles: list[str] = [
        'Fight Club', 'The Big Short', 'The Big Lebowski', 'Donnie Darko',
        'The Bucket List', 'Downfall', 'Good Morning Vietnam',
        'True Grit', 'Forest Gump', 'Good Will Hunting',
        'The Imitation Game', 'The Last Samurai', 'Lawrence of Arabia',
        'Lincoln', 'Little Shop of Horrors', 'Moneyball', 'RV', 'Serenity',
        'Spotlight', 'Downfall'
    ]
    assets: list[dict[str, str | dict[str, any]]] = []
    for counter in range(0, 20):
        created: datetime = datetime.now(tz=UTC) - timedelta(days=counter)
        asset_id: UUID = uuid4()
        cursor: str = cache.get_cursor(member_id, asset_id)

        asset: dict[str, str] = {
            'cursor': cursor,
            'node': {
                'asset_id': str(asset_id),
                'description': 'blah blah blah',
                'title': titles[counter],
                'ingest_status': ['published', 'external'][counter % 2],
                'creator': ['me', 'you'][int(counter / 5) % 2],
                'created_timestamp': created.timestamp()
            }
        }
        await cache.json_set(asset_list, KEY_PREFIX, member_id, asset)
        assets.append(asset)

    return assets


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
