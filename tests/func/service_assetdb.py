'''
Test cases for Query ID cache

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

from byoda.datatypes import DataRequestType

from byoda.datacache.assetcache import AssetCache

from byoda.storage.filestorage import FileStorage

from byoda.servers.service_server import ServiceServer

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger
from byoda.util.paths import Paths

from byoda import config

from tests.lib.setup import get_test_uuid

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID

from podserver.codegen.pydantic_service_4294929430_1 import (
    asset as Asset,
    video_chapter as Video_chapter,
    video_thumbnail as Video_thumbnail,
    claim as Claim,
    monetization as Monetization
)

TEST_DIR = '/tmp/byoda-tests/assetdb'

TEST_ASSET_ID: UUID = '32af2122-4bab-40bb-99cb-4f696da49e26'

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

        network = await Network.create(
            app_config['application']['network'],
            TEST_DIR,
            app_config['svcserver']['private_key_password']
        )

        service_file = network.paths.get(
            Paths.SERVICE_FILE, service_id=ADDRESSBOOK_SERVICE_ID
        )

        service_dir: str = TEST_DIR + '/' + service_file
        os.makedirs(os.path.dirname(service_dir))
        shutil.copy(DUMMY_SCHEMA, service_dir)

        server = await ServiceServer.setup(network, app_config)
        config.server: ServiceServer = server

        await server.service.examine_servicecontract(service_file)
        server.service.name = 'addressbook'
        await server.service.create_secrets(
            network.services_ca, local=True,
            password=app_config['svcserver']['private_key_password']
        )

        storage = FileStorage(app_config['svcserver']['root_dir'])
        await server.load_network_secrets(storage_driver=storage)

        await server.load_secrets(
            app_config['svcserver']['private_key_password']
        )
        await server.load_schema(verify_contract_signatures=False)

        config.trace_server: str = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

    @classmethod
    async def asyncTearDown(self):
        pass

    async def test_redis_native_storage(self):
        server: ServiceServer = config.server
        service: Service = server.service
        service_id: int = service.service_id

        member_id: UUID = get_test_uuid()

        asset: Asset = get_asset()
        asset_data: dict[str, object] = asset.model_dump()

        list_name: str = 'test'
        asset_cache: AssetCache = server.asset_cache
        if await asset_cache.exists(list_name):
            result = await asset_cache.delete(list_name)
            self.assertTrue(result)

        result = await asset_cache.create(list_name)
        self.assertTrue(result)

        now = datetime.now(tz=timezone.utc).timestamp()

        item_count: int = 6
        for n in range(1, item_count):
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

        result = await asset_cache.exists(list_name)
        self.assertTrue(result)

        resp: HttpResponse = await DataApiClient.call(
            service_id, asset_cache.asset_class, action=DataRequestType.QUERY,
            secret=asset_cache.tls_secret, member_id=AZURE_POD_MEMBER_ID,
            network=asset_cache.network_name, query_id=get_test_uuid()
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['total_count'], 2)
        self.assertGreaterEqual(len(data['edges']), 2)

        asset_data: dict[str, object] = data['edges'][0]['node']
        cursor: str = data['edges'][0]['cursor']
        azure_asset = Asset(**asset_data)

        result = await server.asset_cache.rpush(
            list_name, data=asset_data, cursor=cursor, member_id=member_id
        )
        self.assertEqual(result, item_count)
        result = await server.asset_cache.get(list_name)
        self.assertEqual(azure_asset, result.data)

        length = await server.asset_cache.len(list_name)
        self.assertEqual(length, 6)

        expired, renewed = await asset_cache.expire(list_name)
        self.assertEqual(expired, 0)
        self.assertEqual(renewed, 0)

        result = await asset_cache.delete(list_name)
        self.assertTrue(result)

        await asset_cache.close()

    async def test_redis_native_expire(self):
        server: ServiceServer = config.server
        service: Service = server.service
        service_id: int = service.service_id

        member_id: UUID = get_test_uuid()

        asset: Asset = get_asset()
        asset_data: dict[str, object] = asset.model_dump()

        list_name: str = 'test'
        asset_cache: AssetCache = server.asset_cache
        if await asset_cache.exists(list_name):
            result = await asset_cache.delete(list_name)
            self.assertTrue(result)

        result = await asset_cache.create(list_name)
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
        self.assertEqual(result, 1)

        item_count: int = 6
        for n in range(1, item_count):
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


def get_asset(asset_id: str = TEST_ASSET_ID) -> dict[str, object]:
    if not asset_id:
        asset_id = get_test_uuid()
    if not isinstance(asset_id, UUID):
        asset_id = UUID(asset_id)

    thumbnail_1 = Video_thumbnail(
        thumbnail_id=str(get_test_uuid()), width=640, height=480,
        size='640x480', preference='default', url='https://thumbnail_url',
    )
    thumbnail_2 = Video_thumbnail(
        thumbnail_id=str(get_test_uuid()), width=320, height=2480,
        size='320x240', preference='default', url='https://thumbnail2_url',
    )

    chapter_1 = Video_chapter(
        chapter_id=str(get_test_uuid()), start=0.0, end=10.0, title='chapter',
    )

    chapter_2 = Video_chapter(
        chapter_id=str(get_test_uuid()), start=0.0, end=10.0, title='chapter',
    )

    claim_1 = Claim(
        claim_id=str(get_test_uuid()),
        cert_expiration=datetime.now(tz=timezone.utc).isoformat(),
        cert_fingerprint='claim1_fingerprint',
        issuer_id=str(get_test_uuid()),
        issuer_type='app', keyfield='asset_id',
        requester_id=str(get_test_uuid()), requester_type='member',
        keyfield_id=str(asset_id),
        object_fields=['blah1', 'blah12'], object_type='public_assets',
        signature='blah', signature_format_version=1,
        signature_timestamp=datetime.now(tz=timezone.utc).isoformat(),
        signature_url='https://signature_url',
        renewal_url='https://renewal_url',
        confirmation_url='https://confirmation_url',
        claims=['claim11', 'claim12', 'claim13']
    )

    claim_2 = Claim(
        claim_id=str(get_test_uuid()),
        cert_expiration=datetime.now(tz=timezone.utc).isoformat(),
        cert_fingerprint='claim2_fingerprint',
        issuer_id=str(get_test_uuid()),
        issuer_type='app', keyfield='asset_id',
        keyfield_id=str(asset_id),
        object_fields=['blah2', 'blah22'], object_type='public_assets',
        requester_id=str(get_test_uuid()), requester_type='member',
        signature='blah', signature_format_version=1,
        signature_timestamp=datetime.now(tz=timezone.utc).isoformat(),
        signature_url='https://signature2_url',
        renewal_url='https://renewal2_url',
        confirmation_url='https://confirmation2_url',
        claims=['claim21', 'claim22', 'claim23']
    )

    monetization_1 = Monetization(
        monetization_id=str(get_test_uuid()),
        monetization_scheme='free'
    )

    asset = Asset(
        asset_id=asset_id, asset_type='video',
        created_timestamp=datetime.now(tz=timezone.utc),
        asset_merkle_root_hash='1',
        asset_url='https://asset_url',
        channel_id=get_test_uuid(),
        content_warnings=['warning1', 'warning2'],
        contents='contents',
        copyright_years=[102, 1492],
        creator='byoda',
        ingest_status='published',
        published_timestamp=datetime.now(tz=timezone.utc),
        publisher='byoda',
        publisher_asset_id='byoda',
        screen_orientation_horizontal=True,
        title='asset', subject='asset',
        video_thumbnails=[thumbnail_1, thumbnail_2],
        video_chapters=[chapter_1, chapter_2],
        claims=[claim_1, claim_2],
        monetizations=[monetization_1]
    )
    return asset


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
