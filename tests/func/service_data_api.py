'''
Test cases for service data API cache

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023, 2024, 2024
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

from byoda.models.data_api_models import EdgeResponse as Edge
from byoda.models.data_api_models import Channel

from byoda.datatypes import MonetizationType

from byoda.datacache.asset_cache import AssetCache
from byoda.datacache.channel_cache import ChannelCache

from byoda.secrets.secret import Secret

from byoda.storage.filestorage import FileStorage

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
        config_file: str = os.environ.get('CONFIG_FILE', 'config.yml-byotube')
        with open(config_file) as file_desc:
            app_config: dict[str, dict[str, any]] = yaml.safe_load(file_desc)

        config.debug = True

        asset_cache: AssetCache = await AssetCache.setup(
            app_config['svcserver']['asset_cache_readwrite']
        )
        await asset_cache.client.function_flush('SYNC')
        await asset_cache.client.ft(asset_cache.index_name).dropindex()
        await asset_cache.client.delete(AssetCache.LIST_OF_LISTS_KEY)

        list_key: str = asset_cache.get_list_key(TESTLIST)
        keys: list[str] = await asset_cache.client.keys(f'{list_key}*')
        for key in keys:
            await asset_cache.client.delete(key)

        await asset_cache.client.aclose()

        channel_cache: ChannelCache = await ChannelCache.setup(
            app_config['svcserver']['channel_cache_readwrite']
        )
        config.channel_cache = channel_cache
        redis_rw_url: str = app_config['svcserver']['channel_cache_readwrite']
        config.channel_cache_readwrite = await ChannelCache.setup(redis_rw_url)

        asset_cache: AssetCache = await AssetCache.setup(
            app_config['svcserver']['asset_cache']
        )
        config.asset_cache = asset_cache

        service_secret_data: dict[str, str] = \
            app_config['svcserver']['proxy_service_secret']
        config.service_secret = Secret(
            cert_file=service_secret_data['cert_file'],
            key_file=service_secret_data['key_file']
        )

        await config.service_secret.load(
            password=service_secret_data['passphrase'],
            storage_driver=FileStorage('')
        )

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        config.app = setup_api(
            'BYO.Tube test svcserver', 'server for testing service APIs',
            'v0.0.1',
            [
                StatusRouter,
                SearchRouter,
                DataRouter
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        return

    @classmethod
    async def asyncTearDown(self) -> None:
        await ApiClient.close_all()
        await config.channel_cache.close()
        await config.channel_cache_readwrite.close()
        await config.asset_cache.close()

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
            new_asset_data['monetizations'] = [
                {
                    "created_timestamp": datetime.now(tz=UTC),
                    "monetization_id": get_test_uuid(),
                    "monetization_type": MonetizationType.BURSTPOINTS,
                    "require_burst_points": True,
                    "network_relations": [],
                    "payment_options": []
                }
            ]
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
            self.assertEqual(
                data['node']['monetizations'][0]['monetization_type'],
                all_assets[0]['monetizations'][0]['monetization_type'].value
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

    async def test_channel_cache(self) -> None:
        channel_cache: ChannelCache = config.channel_cache

        channel_id: UUID = get_test_uuid()
        created: datetime = datetime.now(tz=UTC)
        creator: str = 'test_creator'
        first_channel = Channel(
            channel_id=channel_id,
            creator=creator,
            created_timestamp=created,
            description='test channel',
            is_family_safe=True,
            keywords=['test', 'channel'],
            annotations=['key1:value1', 'key:2:value2'],
            available_country_codes=['USA'],
            channel_thumbnails=[],
            banners=[],
            external_urls=[],
            claims=[],
            thirdparty_platform_videos=10,
            thirdparty_platform_followers=10000,
            thirdparty_platform_views=1000000
        )
        member_id: UUID = get_test_uuid()
        await channel_cache.add_newest_channel(member_id, first_channel)

        set_key: str = channel_cache.get_set_key(ChannelCache.ALL_CREATORS)
        cursor: str = ChannelCache.get_cursor(member_id, first_channel.creator)
        result = await channel_cache.client.sismember(
            set_key, cursor
        )
        self.assertTrue(result)

        shortcut: str = ChannelCache.get_shortcut_key(
            member_id, creator
        ).split(':')[1]
        shortcut_member_id: str
        shortcut_creator: str
        shortcut_member_id, shortcut_creator = \
            await channel_cache.get_shortcut(shortcut)

        self.assertEqual(shortcut_member_id, member_id)
        self.assertEqual(shortcut_creator, creator)

        api_url: str = 'http://localhost:8000/api/v1/service/channel/shortcut'
        async with AsyncClient(app=config.app) as client:
            resp: HttpResponse = await client.get(
                api_url, params={'shortcut': shortcut},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(UUID(data['member_id']), member_id)
            self.assertEqual(data['creator'], creator)

            resp: HttpResponse = await client.get(
                f'{api_url}_by_value',
                params={'member_id': member_id, 'creator': creator},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsNotNone(data)
            self.assertEqual(data['shortcut'], shortcut)

        api_url: str = 'http://localhost:8000/api/v1/service/channel'
        async with AsyncClient(app=config.app) as client:
            resp: HttpResponse = await client.get(
                api_url, params={
                    'member_id': member_id, 'creator': first_channel.creator
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            node = data.get('node')
            self.assertIsNotNone(node)
            self.assertEqual(node['creator'], first_channel.creator)
            self.assertEqual(
                node['thirdparty_platform_videos'],
                first_channel.thirdparty_platform_videos
            )
            self.assertEqual(
                node['thirdparty_platform_followers'],
                first_channel.thirdparty_platform_followers
            )
            self.assertEqual(
                node['thirdparty_platform_views'],
                first_channel.thirdparty_platform_views
            )

        cursor = None
        member_id = None
        edge: Edge | None = await channel_cache.get_oldest_channel()
        self.assertIsNotNone(edge)

        channel: Channel = edge.node
        cursor = ChannelCache.get_cursor(edge.origin, channel.creator)
        result: int = await channel_cache.client.sismember(
            set_key, cursor
        )
        self.assertFalse(result)

        await channel_cache.add_oldest_channel_back(edge.origin, channel)
        result = await channel_cache.client.sismember(
            set_key, cursor
        )
        self.assertTrue(result)

        channel: Channel = edge.node

        api_url: str = 'http://localhost:8000/api/v1/service/channel'
        async with AsyncClient(app=config.app) as client:
            resp: HttpResponse = await client.get(
                api_url,
                params={'member_id': edge.origin, 'creator': channel.creator},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue('node' in data)
            self.assertGreaterEqual(data['node']['creator'], channel.creator)


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
