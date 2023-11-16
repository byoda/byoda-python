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

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema

from byoda.datacache.asset_cache import AssetCache

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


TEST_DIR = '/tmp/byoda-tests/assetdb'

DUMMY_SCHEMA = 'tests/collateral/addressbook.json'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config_file = os.environ.get('CONFIG_FILE', 'config.yml')
        with open(config_file) as file_desc:
            app_config = yaml.safe_load(file_desc)

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

        service_file = network.paths.get(
            Paths.SERVICE_FILE, service_id=ADDRESSBOOK_SERVICE_ID
        )

        server = await ServiceServer.setup(network, app_config)
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

        await server.setup_asset_cache(app_config['svcserver']['cache'])

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
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_service_data_api(self):
        server: ServiceServer = config.server

        member_id: UUID = get_test_uuid()

        asset: Asset = get_asset()
        asset_data: dict[str, object] = asset.model_dump()

        list_name: str = AssetCache.ASSET_UPLOADED_LIST
        asset_cache: AssetCache = server.asset_cache

        if await asset_cache.exists_list(list_name):
            result = await asset_cache.delete_list(list_name)
            self.assertTrue(result)

        result = await asset_cache.create_list(list_name)
        self.assertTrue(result)

        all_asset_count: int = 110
        all_assets: list[dict[str, UUID | str | int | float | datetime]] = []
        for n in range(0, all_asset_count):
            new_asset_data = copy(asset_data)
            new_asset_data['asset_id'] = str(get_test_uuid())
            result = await asset_cache.lpush(
                list_name, new_asset_data, member_id, f'{n}*test',
            )
            self.assertEqual(result, n + 1)
            all_assets.append(new_asset_data)

        api_url: str = 'http://localhost:8000/api/v1/service/data'
        resp: HttpResponse = await ApiClient.call(api_url, app=config.app)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['total_count'], 25)
        asset_id = data['edges'][0]['node']['asset_id']
        self.assertEqual(
            asset_id, str(all_assets[all_asset_count - 1]['asset_id'])
        )
        self.assertNotEqual(data['edges'][1]['node']['asset_id'], asset_id)

        step: int = 25
        for loop in range(0, 5):
            after = loop * 25
            resp: HttpResponse = await ApiClient.call(
                f'{api_url}?first={step}&after={after}', app=config.app
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
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

        after = 20
        resp: HttpResponse = await ApiClient.call(
            f'http://localhost:8000/api/v1/service/data?after={after}',
            app=config.app
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['total_count'], step)
        self.assertEqual(len(data['edges']), step)

        start_asset_id: str = data['edges'][0]['node']['asset_id']
        end_asset_id: str = data['edges'][step-1]['node']['asset_id']

        all_assets_index = all_asset_count - 1 - after
        self.assertEqual(
            start_asset_id, all_assets[all_assets_index]['asset_id']
        )
        self.assertEqual(
            end_asset_id, all_assets[all_assets_index - step + 1]['asset_id']
        )


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
