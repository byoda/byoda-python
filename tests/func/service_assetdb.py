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

from uuid import UUID
from datetime import datetime
from datetime import timezone

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema

from byoda.datacache.asset_cache import AssetCache

from byoda.storage.filestorage import FileStorage

from byoda.servers.service_server import ServiceServer

from byoda.util.api_client.api_client import ApiClient

from byoda.util.logger import Logger

from byoda.util.paths import Paths

from byoda import config

from tests.lib.setup import get_test_uuid
from tests.lib.util import get_asset

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID

from podserver.codegen.pydantic_service_4294929430_1 import asset as Asset


TEST_DIR = '/tmp/byoda-tests/assetdb'

DUMMY_SCHEMA = 'tests/collateral/addressbook.json'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config_file = os.environ.get('CONFIG_FILE', 'config.yml')
        with open(config_file) as file_desc:
            app_config = yaml.safe_load(file_desc)

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

        await server.setup_asset_cache(app_config['svcserver']['asset_cache'])

        config.trace_server: str = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        return

    @classmethod
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_redis_storage(self):
        server: ServiceServer = config.server

        member_id: UUID = get_test_uuid()

        asset: Asset = get_asset()
        asset_data: dict[str, object] = asset.model_dump()

        list_name: str = 'test'
        asset_cache: AssetCache = server.asset_cache

        if await asset_cache.exists_list(list_name):
            result = await asset_cache.delete_list(list_name)
            self.assertTrue(result)

        result = await asset_cache.create_list(list_name)
        self.assertTrue(result)

        now = datetime.now(tz=timezone.utc).timestamp()

        item_count: int = 6
        for n in range(1, item_count):
            asset_data['asset_id'] = get_test_uuid()
            result = await asset_cache.lpush(
                list_name, asset_data, member_id, f'{n}*test',
                now + (n-1) * 86400
            )
            self.assertEqual(result, n)

        data = await asset_cache.get_range(list_name, 1, 4)
        self.assertEqual(len(data), 3)
        # We pushed items to the front of the list so they
        # end up in reverse order in our range query
        for n in range(5, 2, -1):
            self.assertEqual(data[5-n].cursor, f'{n-1}*test')

        result = await asset_cache.exists_list(list_name)
        self.assertTrue(result)

        resp = await asset_cache._asset_query(AZURE_POD_MEMBER_ID)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['total_count'], 1)
        self.assertGreaterEqual(len(data['edges']), 1)

        asset_data: dict[str, object] = data['edges'][0]['node']
        cursor: str = data['edges'][0]['cursor']
        azure_asset = Asset(**asset_data)

        result = await server.asset_cache.rpush(
            list_name, data=asset_data, cursor=cursor, member_id=member_id
        )
        self.assertEqual(result, item_count)
        result = await server.asset_cache.get(list_name)
        self.assertEqual(
            azure_asset.published_timestamp, result.node.published_timestamp
        )

        length = await server.asset_cache.len(list_name)
        self.assertEqual(length, 6)

        expired, renewed = await asset_cache.expire(list_name)
        self.assertEqual(expired, 1)
        self.assertEqual(renewed, 0)

        result = await asset_cache.delete_list(list_name)
        self.assertTrue(result)

        await asset_cache.close()

    async def test_redis_expire(self):
        server: ServiceServer = config.server

        member_id: UUID = get_test_uuid()

        asset: Asset = get_asset()
        asset_data: dict[str, object] = asset.model_dump()

        list_name: str = 'test'
        asset_cache: AssetCache = server.asset_cache
        if await asset_cache.exists_list(list_name):
            result = await asset_cache.delete_list(list_name)
            self.assertTrue(result)

        result = await asset_cache.create_list(list_name)
        self.assertTrue(result)

        now = datetime.now(tz=timezone.utc).timestamp()

        resp = await asset_cache._asset_query(AZURE_POD_MEMBER_ID)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['total_count'], 1)
        self.assertGreaterEqual(len(data['edges']), 1)

        asset_data: dict[str, object] = data['edges'][0]['node']
        cursor: str = data['edges'][0]['cursor']

        delay: int = 60 * 60
        result = await server.asset_cache.lpush(
            list_name, data=asset_data, cursor=cursor,
            member_id=AZURE_POD_MEMBER_ID, expires=now + delay
        )
        self.assertEqual(result, True)

        item_count: int = 6
        for n in range(1, item_count):
            asset_data['asset_id'] = get_test_uuid()
            previous_delay: int = delay
            delay = 86400 * n
            self.assertGreater(delay, previous_delay)
            result = await asset_cache.lpush(
                list_name, data=asset_data, member_id=member_id,
                cursor=f'{n}*test', expires=now + delay
            )
            self.assertEqual(result, n + 1)
            result = await server.asset_cache.get_range(list_name, 0, 10)
            self.assertEqual(len(result), n + 1)

        expired, renewed = await asset_cache.expire(
            list_name, timestamp=now + 86400 * 2 + 1
        )
        self.assertEqual(expired, 2)
        self.assertEqual(renewed, 1)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
