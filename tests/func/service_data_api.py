'''
Test cases for AssetDb cache

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import yaml
import unittest

from copy import copy
from uuid import UUID
from datetime import UTC
from datetime import datetime

import orjson

from httpx import AsyncClient

from byoda.datacache.asset_cache import AssetCache
from byoda.datacache.searchable_cache import SearchableCache

from byoda.util.fastapi import setup_api

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda import config

from byotubesvr.routers import search as SearchRouter
from byotubesvr.routers import data as DataRouter
from byotubesvr.routers import status as StatusRouter

from tests.lib.setup import get_test_uuid

from byoda.models.data_api_models import Asset

from byotubesvr.routers.data import DEFAULT_PAGING_SIZE

TESTLIST: str = 'testlualist'

TEST_ASSET_ID: UUID = '32af2122-4bab-40bb-99cb-4f696da49e26'

DUMMY_SCHEMA: str = 'tests/collateral/addressbook.json'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        config_file: str = os.environ.get('CONFIG_FILE', 'config-byotube.yml')
        with open(config_file) as file_desc:
            app_config: dict[str, dict[str, any]] = yaml.safe_load(file_desc)

        config.debug = True

        cache: AssetCache = await AssetCache.setup(
            app_config['appserver']['asset_cache']
        )
        await cache.client.function_flush('SYNC')
        await cache.client.ft(cache.index_name).dropindex()
        await cache.client.delete(AssetCache.LIST_OF_LISTS_KEY)

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

        cache: AssetCache = await AssetCache.setup(
            app_config['appserver']['asset_cache']
        )
        config.asset_cache = cache

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        config.app = setup_api(
            'BYO.Tube test appserver', 'server for testing service APIs',
            'v0.0.1',
            [
                SearchRouter,
                StatusRouter,
                DataRouter
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        return

    @classmethod
    async def asyncTearDown(self) -> None:
        await ApiClient.close_all()

    async def test_service_data_api(self) -> None:
        member_id: UUID = get_test_uuid()

        asset: Asset = get_asset()
        asset_data: dict[str, object] = asset.model_dump()

        list_name: str = AssetCache.DEFAULT_ASSET_LIST
        asset_cache: AssetCache = config.asset_cache

        if await asset_cache.exists_list(list_name):
            result: bool = await asset_cache.delete_list(list_name)
            self.assertTrue(result)

        titles: list[str] = ['prank', 'fail', 'review', 'news', 'funny']
        creators: list[str] = [
            'Rick Beato', 'mrbeats', 'Tom Scott' 'Johny Harris', 'SideQuest',
            'TechAltar', 'The Dodo', 'theAdamConover', '_vector_',
            'Polyphonic', 'Numberphile'
        ]
        all_asset_count: int = 110
        test_uuids: list[UUID] = [get_test_uuid() for n in range(0, 55)]
        all_assets: list[dict[str, UUID | str | int | float | datetime]] = []
        for n in range(0, all_asset_count):
            member_id = test_uuids[n % 55]

            category: str = ['news & politics', 'sports', 'music'][n % 3]
            new_asset_data: dict[str, object] = copy(asset_data)
            new_asset_data['asset_id'] = str(get_test_uuid())
            new_asset_data['title'] = titles[n % 5]
            new_asset_data['categories'] = [category]
            new_asset_data['creator'] = f'{creators[n % 10]}-{n}'
            new_asset_data['ingest_status'] = ['external', 'published'][n % 2]
            new_asset_data['published_timestamp'] = datetime.now(tz=UTC)
            await asset_cache.add_newest_asset(
                member_id, new_asset_data
            )
            all_assets.append(new_asset_data)

        api_url: str = 'http://localhost:8000/api/v1/service/data'

        async with AsyncClient(app=config.app) as client:
            resp: HttpResponse = await client.get(api_url)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertGreaterEqual(data['total_count'], DEFAULT_PAGING_SIZE)
            asset_id: str = data['edges'][0]['node']['asset_id']
            self.assertEqual(
                asset_id, str(all_assets[all_asset_count - 1]['asset_id'])
            )
            self.assertNotEqual(data['edges'][1]['node']['asset_id'], asset_id)

            resp: HttpResponse = await client.get(
                api_url, params={'ingest_status': 'published'}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertGreaterEqual(data['total_count'], 25)
            for edge in data['edges']:
                self.assertEqual(
                    edge['node']['ingest_status'], 'published'
                )

            asset_url: str = 'http://localhost:8000/api/v1/service/asset'
            #
            # Get an asset by its member_id & asset_id
            #
            query_param: dict[str, UUID] = {
                'member_id': test_uuids[0],
                'asset_id': all_assets[0]['asset_id']
            }
            resp: HttpResponse = await client.get(
                asset_url, params=query_param
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data['origin'], str(test_uuids[0]))
            self.assertEqual(
                data['node']['asset_id'], all_assets[0]['asset_id']
            )

            # Cause an 404
            query_param = {
                'member_id': test_uuids[0],
                'asset_id': get_test_uuid()
            }
            resp: HttpResponse = await client.get(
                asset_url, params=query_param
            )
            self.assertEqual(resp.status_code, 404)

            #
            # Get an asset by its server-generated cursor
            # (server-generated cursor is different than cursors
            # generated by pods)
            #
            cursor: str = asset_cache.get_cursor(
                test_uuids[0], all_assets[0]['asset_id']
            )

            query_param: dict[str, UUID] = {
                'cursor': cursor,
            }
            resp: HttpResponse = await client.get(
                asset_url, params=query_param
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data['cursor'], cursor)
            self.assertEqual(data['origin'], str(test_uuids[0]))
            self.assertEqual(
                data['node']['asset_id'], all_assets[0]['asset_id']
            )

            # So we've created a list of 110 items by adding items one by end
            # to the front. In the list in the cache, the first item of the
            # list is the last item added. The API returns the first item in
            # the list, so the first first asset returned is the last asset
            # added
            step: int = 25
            after: str | None = None
            for loop in range(0, 5):
                url: str = f'{api_url}?first={step}'
                if after:
                    url += f'&after={after}'
                resp: HttpResponse = await client.get(url)
                self.assertEqual(resp.status_code, 200)
                data: dict[str, any] = resp.json()

                if loop >= 4:
                    self.assertEqual(data['total_count'], 10)
                    self.assertEqual(len(data['edges']), 10)
                else:
                    self.assertEqual(data['total_count'], step)
                    self.assertEqual(len(data['edges']), step)

                api_asset_id: str
                all_asset_id: str
                all_data_index: int
                api_asset_count: int = len(data['edges'])
                for count in range(0, api_asset_count):
                    api_asset_id = data['edges'][count]['node']['asset_id']

                    all_data_index = \
                        (all_asset_count - 1) - (loop * step) - count
                    all_asset_id = str(all_assets[all_data_index]['asset_id'])
                    self.assertEqual(api_asset_id, all_asset_id)

                after: str = data['page_info']['end_cursor']

            # Now we test with filter
            api_url: str = 'http://localhost:8000/api/v1/service/data'

            resp: HttpResponse = await client.get(
                api_url, params={'ingest_status': 'external'})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertGreaterEqual(data['total_count'], 25)
            for edge in data['edges']:
                self.assertEqual(
                    edge['node']['ingest_status'], 'external'
                )

            # Here we'll test search
            api_url: str = 'http://localhost:8000/api/v1/service/search/asset'
            resp: HttpResponse = await client.get(
                f'{api_url}?text={titles[0]}&num=30'
            )
            self.assertEqual(resp.status_code, 200)
            data: dict[str, any] = resp.json()
            self.assertTrue(len(data), 22)

            resp: HttpResponse = await client.get(
                f'{api_url}?text={titles[0]}&offset=5&num=1'
            )
            self.assertEqual(resp.status_code, 200)
            new_data: dict[str, any] = resp.json()
            self.assertTrue(len(new_data), 1)
            self.assertTrue(
                data[5]['node']['asset_id'],
                new_data[0]['node']['asset_id']
            )

            resp: HttpResponse = await client.get(
                f'{api_url}?text={creators[0]}&num=15'
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(len(data), 11)


def get_asset(asset_id: str = TEST_ASSET_ID) -> Asset:
    '''
    Creates and returns an asset object with dummy data.
    '''

    with open('tests/collateral/dummy_asset.json') as file_desc:
        data: str = file_desc.read()
        asset_data: dict[str, any] = orjson.loads(data)
        asset: Asset = Asset(**asset_data)

    if not asset_id:
        asset_id = get_test_uuid()
    if not isinstance(asset_id, UUID):
        asset_id = UUID(asset_id)

    asset.asset_id = asset_id
    return asset


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
