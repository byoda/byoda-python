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

from uuid import UUID
from uuid import uuid4
from datetime import datetime
from datetime import timedelta
from datetime import UTC

import orjson

from redis.commands.search.result import Result

from byoda.datamodel.memberdata import EdgeResponse as Edge

from byoda.datacache.searchable_cache import SearchableCache
from byoda.datacache.asset_cache import AssetCache

from byoda.util.logger import Logger

REDIS_URL: str = os.getenv('REDIS_URL', 'redis://192.168.1.13:6379')

TESTLIST: str = 'testlualist'


class TestServiceAssetCache(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def asyncSetUp() -> None:
        if '192.168.1' not in REDIS_URL:
            raise ValueError(
                'This test should only be run against '
                f'a test redis server: {REDIS_URL}'
            )
        cache: AssetCache = await AssetCache.setup(REDIS_URL)

        await cache.client.flushdb()
        await cache.client.function_flush('SYNC')
        try:
            await cache.client.ft(cache.index_name).dropindex()
        except Exception:
            pass

        await cache.client.delete(AssetCache.LIST_OF_LISTS_KEY)

        await cache.delete_list(AssetCache.ALL_ASSETS_LIST)

        list_key: str = cache.get_list_key(TESTLIST)
        keys: list[str] = await cache.client.keys(f'{list_key}*')
        for key in keys:
            await cache.client.delete(key)

        keys: list[str] = await cache.client.keys(
            f'{ AssetCache.ASSET_KEY_PREFIX}*'
        )

        for key in keys:
            await cache.client.delete(key)

        await cache.client.aclose()

    @staticmethod
    async def asyncTearDown() -> None:
        pass

    async def test_asset_model(self) -> None:
        with open('tests/collateral/dummy_asset.json', 'r') as file:
            data: dict[str, any] = orjson.loads(file.read())

        # We need to update the timestamp to ensure the asset gets added
        # to the 'recent_uploads' list.
        data['published_timestamp'] = datetime.now(tz=UTC).timestamp() - 7200

        cache: AssetCache = await AssetCache.setup(REDIS_URL)

        member_id: UUID = uuid4()
        await cache.add_newest_asset(member_id, data)
        counter: int
        for counter in range(0, 10):
            # We need to change the member_id to make sure that the
            # cursor is unique.
            member_id = uuid4()
            data['creator'] = f'Asset creator {counter}'
            data['asset_id'] = str(uuid4())
            await cache.add_newest_asset(member_id, data)

        lists: set[str] = await cache.get_list_of_lists()
        self.assertIsNotNone(lists)
        self.assertEqual(len(lists), 31)

        creators: set[str] = await cache.get_creators_list()
        self.assertIsNotNone(creators)
        self.assertEqual(len(creators), 11)

        results: list[Edge] = await cache.get_list_assets()
        self.assertEqual(len(results), 11)

        cursor: str = results[0].cursor
        expires: int = await cache.get_asset_expiration(cursor)
        self.assertTrue(expires > 3600)

        item: str | None = await cache.get_oldest_asset()
        result: int = await cache.add_oldest_asset(item)
        self.assertEqual(result, 11)
        await cache.close()

    async def test_lua_get_list_values(self) -> None:
        '''
        These tests execute the Redis CLI to feed it a Lua script that
        performs the same function as the get_list_values() method of
        '''

        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)
        self.assertIsNotNone(cache)

        member_id: UUID = uuid4()

        assets: list[dict[str, str | dict[str, any]]] = await populate_cache(
            cache, TESTLIST, member_id
        )

        data: list[dict[str, any]]

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

        filter_name = 'ingest_status'
        filter_value = 'external'
        data = call_lua_script(
            self, filter_name=filter_name, filter_value=filter_value
        )
        self.assertEqual(len(data), 10)

        await cache.close()

    async def test_search_searchable_cache(self) -> None:
        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)

        member_id: UUID = uuid4()

        await populate_cache(
            cache, TESTLIST, member_id
        )
        result: Result = \
            await cache.client.ft(cache.index_name).search('Fight')

        self.assertEqual(result.total, 1)
        self.assertEqual(len(result.docs), 1)

        await cache.close()

    async def test_search_asset_cache(self) -> None:
        cache: AssetCache = await AssetCache.setup(REDIS_URL)

        member_id: UUID = uuid4()
        await populate_cache(
            cache, TESTLIST, member_id
        )

        results: list[Edge] = await cache.search('Fight')

        self.assertEqual(len(results), 1)

        await cache.close()

    async def test_pagination(self) -> None:
        cache: SearchableCache = await SearchableCache.setup(REDIS_URL)

        member_id: UUID = uuid4()

        assets: list[dict[str, str | dict[str, any]]] = await populate_cache(
            cache, TESTLIST, member_id
        )

        data: list
        data = await cache.get_list_values(
            TESTLIST, AssetCache.ASSET_KEY_PREFIX
            )
        self.assertEqual(len(data), 20)

        data = await cache.get_list_values(
            TESTLIST,  AssetCache.ASSET_KEY_PREFIX, after=assets[5]['cursor'],
            first=5
        )
        self.assertEqual(len(data), 5)

        data = await cache.get_list_values(
            TESTLIST,  AssetCache.ASSET_KEY_PREFIX, after=assets[5]['cursor'],
            first=10
        )
        self.assertEqual(len(data), 5)

        data = await cache.get_list_values(
            TESTLIST,  AssetCache.ASSET_KEY_PREFIX, after=assets[15]['cursor']
        )
        self.assertEqual(len(data), 15)

        data = await cache.get_list_values(
            TESTLIST,  AssetCache.ASSET_KEY_PREFIX, after=assets[16]['cursor'],
            filter_name='ingest_status', filter_value='external'
        )
        self.assertEqual(len(data), 8)

        await cache.close()


def call_lua_script(test, first: int = 25, after: str | None = None,
                    filter_name: str | None = None,
                    filter_value: str | None = None) -> list[dict[str, any]]:
    if after and not first:
        raise ValueError('Cannot specify "after" without "first"')

    # The comma in the parameters to 'redis-cli' separate the 'KEYS'
    # from the 'ARGV' arguments, see:
    # https://redis.io/docs/interact/programmability/lua-debugging/
    cmd: list[str] = [
        'redis-cli', '-3', '-u', REDIS_URL,
        '--eval', AssetCache.LUA_FUNCTIONS_FILE,
        f'lists:{TESTLIST}', ',', AssetCache.ASSET_KEY_PREFIX,
        f'{first}', f'{after}'
    ]

    if filter_name:
        cmd.extend([filter_name, filter_value])

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
        created: datetime = datetime.now(tz=UTC) - timedelta(hours=counter)
        asset_id: UUID = uuid4()
        cursor: str = cache.get_cursor(member_id, asset_id)
        creator: str = ['me', 'you'][int(counter / 5) % 2] + '-' + str(counter)

        asset_edge: dict[str, str] = {
            'cursor': cursor,
            'origin': str(member_id),
            'node': {
                'asset_id': str(asset_id),
                'description': 'blah blah blah',
                'asset_type': 'video',
                'title': titles[counter],
                'ingest_status': ['published', 'external'][counter % 2],
                'creator': creator,
                'created_timestamp': created.timestamp()
            }
        }
        await cache.json_set(
            [asset_list], SearchableCache.ASSET_KEY_PREFIX, asset_edge
        )
        assets.append(asset_edge)

    return assets


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
