'''
Test cases for AssetDb cache

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import yaml
import shutil
import unittest

from copy import copy
from uuid import UUID
from datetime import datetime

from httpx import AsyncClient

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema

from byoda.datacache.asset_cache import AssetCache
from byoda.datacache.searchable_cache import SearchableCache

from byoda.storage.filestorage import FileStorage

from byoda.servers.service_server import ServiceServer

from byoda.util.fastapi import setup_api

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda.util.paths import Paths

from byoda import config

from svcserver.routers import service as ServiceRouter
from svcserver.routers import member as MemberRouter
from svcserver.routers import search as SearchRouter
from svcserver.routers import data as DataRouter
from svcserver.routers import status as StatusRouter

from tests.lib.setup import get_test_uuid
from tests.lib.util import get_asset

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from podserver.codegen.pydantic_service_4294929430_1 import asset as Asset


TEST_DIR: str = '/tmp/byoda-tests/assetdb'

TESTLIST: str = 'testlualist'

DUMMY_SCHEMA: str = 'tests/collateral/addressbook.json'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        config_file: str = os.environ.get('CONFIG_FILE', 'config.yml')
        with open(config_file) as file_desc:
            app_config: dict[str, dict[str, any]] = yaml.safe_load(file_desc)

        config.debug = True

        app_config['svcserver']['root_dir'] = TEST_DIR

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        network = Network(
            app_config['svcserver'], app_config['application']
        )

        network.paths = Paths(
            network=network.name,
            root_directory=app_config['svcserver']['root_dir']
        )

        service_file: str = network.paths.get(
            Paths.SERVICE_FILE, service_id=ADDRESSBOOK_SERVICE_ID
        )

        server: ServiceServer = await ServiceServer.setup(network, app_config)
        storage = FileStorage(app_config['svcserver']['root_dir'])
        await server.load_network_secrets(storage_driver=storage)

        shutil.copytree(
            'tests/collateral/local/addressbook-service/service-4294929430',
            f'{TEST_DIR}/network-byoda.net/services/service-4294929430'
        )
        shutil.copytree(
            'tests/collateral/local/addressbook-service/private/',
            f'{TEST_DIR}/private'
        )

        service_dir: str = TEST_DIR + '/' + service_file
        shutil.copy(DUMMY_SCHEMA, service_dir)

        await server.load_secrets(
            password=app_config['svcserver']['private_key_password']
        )
        config.server = server

        await server.service.examine_servicecontract(service_file)
        server.service.name = 'addressbook'

        service: Service = server.service
        service.tls_secret.save_tmp_private_key()

        if not await service.paths.service_file_exists(service.service_id):
            await service.download_schema(save=True)

        await server.load_schema(verify_contract_signatures=False)
        schema: Schema = service.schema
        schema.get_data_classes(with_pubsub=False)
        schema.generate_data_models('svcserver/codegen', datamodels_only=True)

        cache: SearchableCache = await SearchableCache.setup(
            app_config['svcserver']['asset_cache']
        )

        await cache.client.function_flush('SYNC')
        await cache.client.ft(cache.index_name).dropindex()
        await cache.client.delete(AssetCache.LIST_OF_LISTS_KEY)

        list_key: str = cache.get_list_key(TESTLIST)
        keys: list[str] = await cache.client.keys(f'{list_key}*')
        for key in keys:
            await cache.client.delete(key)

        keys: list[str] = await cache.client.keys(
            f'{SearchableCache.KEY_PREFIX}*'
        )
        for key in keys:
            await cache.client.delete(key)

        await cache.client.aclose()

        await server.setup_asset_cache(app_config['svcserver']['asset_cache'])

        config.trace_server: str = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        config.app = setup_api(
            'Byoda test svcserver', 'server for testing service APIs',
            'v0.0.1',
            [
                ServiceRouter,
                MemberRouter,
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
        server: ServiceServer = config.server

        member_id: UUID = get_test_uuid()

        asset: Asset = get_asset()
        asset_data: dict[str, object] = asset.model_dump()

        list_name: str = AssetCache.DEFAULT_ASSET_LIST
        asset_cache: AssetCache = server.asset_cache

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
        all_assets: list[dict[str, UUID | str | int | float | datetime]] = []
        for n in range(0, all_asset_count):
            new_asset_data: dict[str, object] = copy(asset_data)
            new_asset_data['asset_id'] = str(get_test_uuid())
            new_asset_data['title'] = titles[n % 5]
            new_asset_data['creator'] = creators[n % 10]
            new_asset_data['ingest_status'] = ['external', 'published'][n % 2]
            await asset_cache.add_asset(
                member_id, new_asset_data
            )
            all_assets.append(new_asset_data)

        api_url: str = 'http://localhost:8000/api/v1/service/data'

        resp: HttpResponse = await ApiClient.call(api_url, app=config.app)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['total_count'], 25)
        asset_id: str = data['edges'][0]['node']['asset_id']
        self.assertEqual(
            asset_id, str(all_assets[all_asset_count - 1]['asset_id'])
        )
        self.assertNotEqual(data['edges'][1]['node']['asset_id'], asset_id)

        resp: HttpResponse = await ApiClient.call(
            api_url, params={'ingest_status': 'published'}, app=config.app)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['total_count'], 25)
        for edge in data['edges']:
            self.assertEqual(
                edge['node']['ingest_status'], 'published'
            )

        # So we've created a list of 110 items by adding items one by end to
        # the front. In the list in the cache, the first item of the list is
        # the last item added. The API returns the first item in the list,
        # so the first first asset returned is the last asset added
        step: int = 25
        after: str | None = None
        for loop in range(0, 5):
            url: str = f'{api_url}?first={step}'
            if after:
                url += f'&after={after}'
            resp: HttpResponse = await ApiClient.call(
                url, app=config.app
            )
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

                all_data_index = (all_asset_count - 1) - (loop * step) - count
                all_asset_id = str(all_assets[all_data_index]['asset_id'])
                self.assertEqual(api_asset_id, all_asset_id)

            after: str = data['page_info']['end_cursor']

        # Now we test with filter
        api_url: str = 'http://localhost:8000/api/v1/service/data'

        resp: HttpResponse = await ApiClient.call(
            api_url, params={'ingest_status': 'external'}, app=config.app)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['total_count'], 25)
        for edge in data['edges']:
            self.assertEqual(
                edge['node']['ingest_status'], 'external'
            )

        # Here we'll test search
        api_url: str = 'http://localhost:8000/api/v1/service/search/asset'
        async with AsyncClient(app=config.app) as client:
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


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
