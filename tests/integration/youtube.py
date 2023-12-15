#!/usr/bin/env python3

'''
Test case for YouTube import of assets and their metadata

For importing video and audio tracks, BenTo4 needs to be installed
under /podserver/bento4: https://www.bento4.com/downloads/

'''

import os
import sys
import shutil
import unittest

from datetime import datetime
from datetime import timezone

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.dataclass import SchemaDataItem

from byoda.datatypes import IngestStatus
from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType

from byoda.requestauth.jwt import JWT

from byoda.datastore.data_store import DataStore

from byoda.data_import.youtube import YouTube
from byoda.data_import.youtube_video import YouTubeVideo

from byoda.storage.filestorage import FileStorage

from byoda.util.api_client.api_client import ApiClient

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars

from tests.lib.auth import get_member_auth_header

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import MODTEST_FQDN, MODTEST_APP_ID

_LOGGER = None

TEST_DIR = '/tmp/byoda-tests/yt-import'

TEST_YOUTUBE_VIDEO_ID: str = '5Y9L5NBINV4'

API_KEY_FILE: str = 'tests/collateral/local/youtube-data-api.key'


class TestFileStorage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        asset_dir: str = f'{TEST_DIR}/tmp/{TEST_YOUTUBE_VIDEO_ID}'
        try:
            shutil.rmtree(asset_dir)
        except FileNotFoundError:
            pass

        shutil.copytree('tests/collateral/local/video_asset', asset_dir)

        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)

        config.test_case = 'TEST_CLIENT'
        config.disable_pubsub = True

        account: Account = await setup_account(
            network_data, clean_pubsub=False,
            local_service_contract=os.environ.get('LOCAL_SERVICE_CONTRACT')
        )

        config.trace_server: str = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        global APP
        APP = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [
                AccountRouter, MemberRouter, AuthTokenRouter,
                AccountDataRouter
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        config.app = APP

        server: PodServer = config.server
        data_store: DataStore = server.data_store
        cache_store: DataStore = server.cache_store
        for member in account.memberships.values():
            await member.enable_data_apis(APP, data_store, cache_store)

        os.environ[YouTube.ENVIRON_CHANNEL] = ''
        os.environ[YouTube.ENVIRON_API_KEY] = ''

    @classmethod
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_scrape_videos(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        schema: Schema = member.schema
        data_classes: dict[str, SchemaDataItem] = schema.data_classes
        class_name: str = YouTubeVideo.DATASTORE_CLASS_NAME
        data_class: SchemaDataItem = data_classes[class_name]

        server: PodServer = config.server
        data_store: DataStore = server.data_store
        storage_driver: FileStorage = server.storage_driver
        network: Network = server.network

        channel: str = 'Dathes:ALL'
        # channel: str = 'accountabletech'
        # channel: str = 'PolyMatter'
        # channel: str = 'History Matters'
        # os.environ[YouTube.ENVIRON_CHANNEL] = f'{channel}:ALL'
        os.environ[YouTube.ENVIRON_CHANNEL] = f'{channel}'
        yt = YouTube()
        ingested_videos = await YouTube.load_ingested_videos(
            member.member_id, data_class, data_store
        )
        self.assertEqual(len(ingested_videos), 0)

        ingested_videos = {
            '2BqKA3DOilk': {
                'ingest_status': IngestStatus.PUBLISHED
            },
            'OD08BC26QaM': {
                'ingest_status': IngestStatus.EXTERNAL
            },
        }
        channel_name: str = channel
        if ':' in channel_name:
            channel_name = channel_name.split(':')[0]
        await yt.get_videos(ingested_videos)
        self.assertGreaterEqual(len(yt.channels[channel_name].videos), 1)

        jwt = JWT.create(
            member.member_id, IdType.MEMBER, member.data_secret, network.name,
            ADDRESSBOOK_SERVICE_ID, IdType.APP, MODTEST_APP_ID,
            expiration_days=3
        )
        mod_url = f'https://{MODTEST_FQDN}'
        mod_api_url: str = mod_url + YouTube.MODERATION_REQUEST_API
        mod_claim_url: str = mod_url + YouTube.MODERATION_CLAIM_URL
        await yt.persist_videos(
            member, storage_driver, ingested_videos,
            moderate_request_url=mod_api_url,
            moderate_jwt_header=jwt.encoded,
            moderate_claim_url=mod_claim_url,
            ingest_interval=4
        )

        ingested_videos = await YouTube.load_ingested_videos(
            member.member_id, data_class, data_store
        )
        self.assertGreaterEqual(len(ingested_videos), 2)

        # See if we can QUERY the data API and get the right result back
        # to confirm the asset was ingested, including the moderation status
        member_auth: dict[str, str] = await get_member_auth_header(
            service_id, APP
        )
        resp: HttpResponse = await DataApiClient.call(
            service_id, 'public_assets', DataRequestType.QUERY,
            headers=member_auth, app=APP,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(len(data), 2)
        self.assertEqual(len(data['edges'][0]['node']['claims']), 1)

        # Start with clean slate
        yt = YouTube()

        await yt.get_videos(ingested_videos)

        await yt.persist_videos(
            member, storage_driver, ingested_videos, ingest_interval=4
        )

    async def test_import_videos(self):
        _LOGGER.info('Disabled API import tests')
        return

        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        server: PodServer = config.server
        data_store: DataStore = server.data_store
        storage_driver: FileStorage = server.storage_driver

        with open(API_KEY_FILE, 'r') as file_desc:
            api_key = file_desc.read().strip()

        os.environ[YouTube.ENVIRON_API_KEY] = api_key
        os.environ[YouTube.ENVIRON_CHANNEL] = 'Dathes'
        yt = YouTube()

        already_ingested_videos = await YouTube.load_ingested_videos(
            member.member_id, data_store
        )
        self.assertEqual(len(already_ingested_videos), 0)

        already_ingested_videos = {
            '2BqKA3DOilk': {
                'ingest_status': IngestStatus.PUBLISHED,
                'published_timestamp': datetime.now(timezone.utc)
            },
            'OD08BC26QaM': {
                'ingest_status': IngestStatus.EXTERNAL,
                'published_timestamp': datetime.now(timezone.utc)
            },
        }

        await yt.get_videos(already_ingested_videos)

        await yt.persist_videos(
            member, storage_driver, already_ingested_videos
        )

        ingested_videos = await YouTube.load_ingested_videos(
            member.member_id, data_store
        )

        # We are not ingesting A/V tracks in this test so only
        # expect 1 ingested video
        self.assertEqual(len(ingested_videos), 1)

        # Start with clean slate
        yt = YouTube()

        await yt.get_videos(ingested_videos)

        await yt.persist_videos(
            member, storage_driver, already_ingested_videos
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
