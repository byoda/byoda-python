'''
Test the LUA script for getting the data of a list of assets

This test requires:
- installation of the redis-tools package with the 'redis-cli' command
- a running Redis server at '192.168.1.13:6379' without a
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

# from byoda.datacache.searchable_cache import SearchableCache.ASSET_KEY_PREFIX
from byoda.datacache.searchable_cache import SearchableCache
# from byoda.datacache.asset_cache import AssetNode
from byoda.util.logger import Logger

LUA_SCRIPT_FILEPATH: str = 'byotubesvr/redis.lua'

REDIS_URL: str = os.getenv('REDIS_URL', 'redis://192.168.1.13:6379')

TESTLIST: str = 'testlualist'

ORIGINS: list[UUID] = [uuid4() for _ in range(0, 100)]


class TestRedisLuaScript(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def asyncSetUp() -> None:
        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)

        await cache.client.function_flush('SYNC')
        await cache.client.ft(cache.index_name).dropindex()
        await cache.client.flushdb()
        list_key: str = cache.get_list_key(TESTLIST)
        keys: list[str] = await cache.client.keys(f'{list_key}*')
        for key in keys:
            await cache.client.delete(key)

        keys: list[str] = await cache.client.keys(
            f'{SearchableCache.ASSET_KEY_PREFIX}*'
        )
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
        self.assertEqual(len(data), 30)

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

        await populate_cache(cache, TESTLIST, member_id)
        results = await cache.client.ft(cache.index_name).search('Fight')

        self.assertEqual(results.total, 1)
        self.assertEqual(len(results.docs), 1)

        await cache.close()

    async def test_avoid_multiple_assets_of_same_origin(self) -> None:
        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)

        member_id: UUID = uuid4()

        assets: list[dict[str, str | dict[str, any]]] = await populate_cache(
            cache, TESTLIST, member_id, [10, 30]
        )

        data: list
        data = await cache.get_list_values(
            TESTLIST, SearchableCache.ASSET_KEY_PREFIX, first=40
        )
        # We created assets with duplicate origin values in positions 10 and 30
        # so you would think the list should contain 40 - 2 = 38 items but
        # that's not actually true; we only check the first 20 items for
        # duplicate creators so at item 30, we already don't see the earlier
        # duplicates in the list so item 30 does get added to the list so the
        # end result is 39 items, with item 0 and item 29 from the same creator
        self.assertEqual(len(data), 39)
        self.assertEqual(
            data[9]['node']['creator'], data[38]['node']['creator']
        )

        data = await cache.get_list_values(
            assets[10]['node']['creator'], SearchableCache.ASSET_KEY_PREFIX,
        )
        # We populated the cache with 40 assets, three of them have the
        # same creator, so the list for the creator should contain 3 items
        self.assertEqual(len(data), 3)

        await cache.close()

    async def test_pagination(self) -> None:
        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)

        member_id: UUID = uuid4()

        assets: list[dict[str, str | dict[str, any]]] = await populate_cache(
            cache, TESTLIST, member_id
        )

        data: list
        data = await cache.get_list_values(
            TESTLIST, SearchableCache.ASSET_KEY_PREFIX
        )
        self.assertEqual(len(data), 20)

        data = await cache.get_list_values(
            TESTLIST, SearchableCache.ASSET_KEY_PREFIX,
            after=assets[5]['cursor'], first=5
        )
        self.assertEqual(len(data), 5)

        data = await cache.get_list_values(
            TESTLIST, SearchableCache.ASSET_KEY_PREFIX,
            after=assets[5]['cursor'], first=10
        )
        self.assertEqual(len(data), 5)

        data = await cache.get_list_values(
            TESTLIST, SearchableCache.ASSET_KEY_PREFIX,
            after=assets[15]['cursor']
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
        f'lists:{TESTLIST}', ',', SearchableCache.ASSET_KEY_PREFIX
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
                         member_id: UUID, dupe_origins: list[int] = []
                         ) -> list[dict]:
    titles: list[str] = [
        'Fight Club', 'The Big Short', 'The Big Lebowski', 'Donnie Darko',
        'The Bucket List', 'Downfall', 'Good Morning Vietnam',
        'True Grit', 'Forest Gump', 'Good Will Hunting',
        'The Imitation Game', 'The Last Samurai', 'Lawrence of Arabia',
        'Lincoln', 'Little Shop of Horrors', 'Moneyball', 'RV', 'Serenity',
        'Spotlight', 'Downfall', 'The color of money', 'The dark knight',
        'Se7en', 'The usual suspects', 'The departed', 'Life is beautiful',
        'The pianist', 'The green mile', 'The shawshank redemption',
        'The godfather', 'The godfather II', 'The godfather III',
        'The silence of the lambs', 'Saving private Ryan', 'Schindler\'s list',
        'Gladiator', 'The patriot', 'The last of the mohicans',
        'Whiplast', 'The social network' 'Wall-E', 'Wolf of Wall Street',
    ]
    creators: list[str] = [
        'someone', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'p9', 'p10',
        'p11', 'p12', 'p13', 'p14', 'p15', 'p16', 'p17', 'p18', 'p19', 'p20',
        'p21', 'p22', 'p23', 'p24', 'p25', 'p26', 'p27', 'p28', 'p29', 'p30',
        'p31', 'p32', 'p33', 'p34', 'p35', 'p36', 'p37', 'p38', 'p39', 'p40',
    ]
    assets: list[dict[str, str | dict[str, any]]] = []
    for counter in range(0, 40):
        created: datetime = datetime.now(tz=UTC) - timedelta(days=counter)
        asset_id: UUID = uuid4()
        cursor: str = cache.get_cursor(member_id, asset_id)

        asset: dict[str, str] = {
            'cursor': cursor,
            'origin': str(ORIGINS[counter]),
            'node': {
                'asset_id': str(asset_id),
                'description': 'blah blah blah',
                'title': titles[counter],
                'ingest_status': ['published', 'external'][counter % 2],
                'creator': creators[counter % len(creators)],
                'created_timestamp': created.timestamp()
            }
        }
        if counter in dupe_origins:
            # We create assets with duplicate origins so we can test
            # that 'SearchableCache.check_head_of_list avoids adding
            # multiple assets with the same origin member_id
            asset['origin'] = assets[0]['origin']
            asset['node']['creator'] = assets[0]['node']['creator']

        await cache.json_set(
            [asset_list, asset['node']['creator']],
            SearchableCache.ASSET_KEY_PREFIX, asset
        )
        assets.append(asset)

    return assets


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
