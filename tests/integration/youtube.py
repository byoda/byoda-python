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

from uuid import uuid4
from datetime import UTC
from datetime import datetime

from byoda.data_import.youtube_channel import YouTubeChannel

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.dataclass import SchemaDataItem
from byoda.datamodel.table import Table

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

from tests.lib.defines import BYOTUBE_SERVICE_ID
from tests.lib.defines import MODTEST_FQDN, MODTEST_APP_ID

_LOGGER = None

TEST_DIR = '/tmp/byoda-tests/yt-import'

TEST_YOUTUBE_VIDEO_ID: str = '5Y9L5NBINV4'

# The video in this directory is used to test generating
# multiple manifest files
TEST_ASSET_DIR: str = 'tests/collateral/local/asset-dtp6b76pMak'


BENTO4_DIRECTORY: str = '../bento4'

API_KEY_FILE: str = 'tests/collateral/local/youtube-data-api.key'


class TestYouTubeDownloads(unittest.IsolatedAsyncioTestCase):
    '''
    Tests for downloading videos and metadata from YouTube
    '''

    async def asyncSetUp(self) -> None:
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

        os.makedirs(f'{TEST_DIR}/tests/collateral', exist_ok=True)
        shutil.copy(
            'tests/collateral/byotube.json', f'{TEST_DIR}/tests/collateral/'
        )
        shutil.copy(
            'tests/collateral/addressbook.json',
            f'{TEST_DIR}/tests/collateral/'
        )

        mock_environment_vars(TEST_DIR, hash_password=False)
        network_data: dict[str, str] = await setup_network(
            delete_tmp_dir=False
        )

        config.test_case = 'TEST_CLIENT'
        config.disable_pubsub = True

        account: Account = await setup_account(
            network_data, clean_pubsub=False, service_id=BYOTUBE_SERVICE_ID,
            local_service_contract=os.environ.get('LOCAL_SERVICE_CONTRACT')
        )

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        os.makedirs(
            f'{TEST_DIR}/network-byoda.net/services/service-16384',
            exist_ok=True
        )
        shutil.copy(
            'tests/collateral/byotube.json',
            (
                f'{TEST_DIR}/network-byoda.net/services/service-16384'
                '/service-contract.json'
            )
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
        server.cdn_fqdn = 'cdn.byo.tube'
        server.cdn_origin_site_id = 'xx'

        data_store: DataStore = server.data_store
        cache_store: DataStore = server.cache_store
        for member in account.memberships.values():
            await member.enable_data_apis(APP, data_store, cache_store)

        os.environ[YouTube.ENVIRON_CHANNEL] = ''
        os.environ[YouTube.ENVIRON_API_KEY] = ''

    @classmethod
    async def asyncTearDown(cls) -> None:
        '''
        Shut down the API client
        '''

        await ApiClient.close_all()

    async def atest_find_value(self) -> None:
        '''
        Unit test for finding a value in a nested dictionary
        '''

        data: dict = {
            'level-1': {
                'level-2': {
                    'level-3': 'some value'
                }
            }
        }
        result: list[str] | None = YouTubeChannel._find_value(data, 'value')
        self.assertEqual(
            result, ['level-1', 'level-2', 'level-3', 'some value']
        )

        data = {
            'level-1': [
                {
                    'level-2[0]': {
                        'level-3': 'no matchalue'
                    }
                },
                {
                    'level-2[1]': {
                        'level-3': 'some value'
                    }
                },
            ]
        }

        result = YouTubeChannel._find_value(data, 'value')
        self.assertEqual(
            result, ['level-1', '[]', 'level-2[1]', 'level-3', 'some value']
        )

    async def atest_content_categories(self) -> None:
        '''
        Test the content categories
        '''

        account: Account = config.server.account
        service_id: int = BYOTUBE_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        schema: Schema = member.schema
        data_classes: dict[str, SchemaDataItem] = schema.data_classes

        server: PodServer = config.server
        data_store: DataStore = server.data_store
        storage_driver: FileStorage = server.storage_driver

        data_class: SchemaDataItem = \
            data_classes[YouTubeVideo.DATASTORE_CLASS_NAME]
        video_table: Table = data_store.get_table(
            member.member_id, data_class.name
        )

        video: YouTubeVideo = await YouTubeVideo.scrape(
            'dtp6b76pMak', True, 'Marques Brownlee', None
        )
        await video.persist(
            member=member, storage_driver=storage_driver, ingest_asset=True,
            video_table=video_table, bento4_directory=BENTO4_DIRECTORY,
            moderate_request_url=None, moderate_jwt_header=None,
            moderate_claim_url=None, custom_domain=None,
            _test_asset_dir=TEST_ASSET_DIR

        )

    async def atest_scrape_unavailable_video(self) -> None:
        '''
        Test scraping a video that is unavailable
        '''

        video_id: str = 'JZ9Qj7bGizA'
        video: YouTubeVideo = await YouTubeVideo.scrape(
            video_id, None, None, None
        )
        self.assertIsNotNone(video)
        self.assertIsNotNone(video.asset_id)
        self.assertEqual(video.ingest_status, IngestStatus.UNAVAILABLE)
        self.assertEqual(video.video_id, video_id)

    async def test_get_channelname(self) -> None:
        '''
        Test getting the channel name from a video
        '''

        channel_name: str = 'LegalEagle'
        ytc = YouTubeChannel(name=channel_name)
        page_data: str = await ytc.get_videos_page()
        ytc.parse_channel_info(page_data)
        self.assertIsNotNone(ytc)
        self.assertEqual(ytc.title, channel_name)
        self.assertEqual(ytc.youtube_channel_id, 'UCpa-Zb0ZcQjTCPP1Dx_1M8Q')
        # this banners test is flakey as scrape does not always include
        # expected 'c4TabbedHeaderRenderer' in the page_data
        # self.assertEqual(len(ytc.banners), 16)
        self.assertEqual(ytc.channel_thumbnail.size, '160x160')
        self.assertEqual(len(ytc.channel_thumbnails), 3)
        self.assertTrue(
            ytc.description.startswith(
                'History Matters is a history-focused'
            )
        )
        self.assertEqual(len(ytc.external_urls), 2)
        self.assertEqual(len(ytc.keywords), 1)
        self.assertIn('Education', ytc.keywords)

    async def atest_scrape_channel(self) -> None:
        account: Account = config.server.account
        service_id: int = BYOTUBE_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        schema: Schema = member.schema
        data_classes: dict[str, SchemaDataItem] = schema.data_classes
        class_name: str = YouTubeVideo.DATASTORE_CLASS_NAME
        data_class: SchemaDataItem = data_classes[class_name]

        server: PodServer = config.server
        data_store: DataStore = server.data_store
        storage_driver: FileStorage = server.storage_driver

        video_table: Table = data_store.get_table(
            member.member_id, data_class.name
        )

        channel: str = 'Dathes'

        await channel.scrape(
            member, data_store, storage_driver, video_table,
            BENTO4_DIRECTORY,
            moderate_request_url=None,
            moderate_jwt_header=None,
            moderate_claim_url=None,
            ingest_interval=None,
            custom_domain='test.byoda.me',
            max_videos_per_channel=10,
        )

    async def atest_scrape_videos(self) -> None:
        '''
        Test scraping a video that is available
        '''

        account: Account = config.server.account
        service_id: int = BYOTUBE_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        schema: Schema = member.schema
        data_classes: dict[str, SchemaDataItem] = schema.data_classes
        class_name: str = YouTubeVideo.DATASTORE_CLASS_NAME
        data_class: SchemaDataItem = data_classes[class_name]

        server: PodServer = config.server
        data_store: DataStore = server.data_store
        storage_driver: FileStorage = server.storage_driver
        network: Network = server.network

        channel: str = 'Dathes'
        # channel: str = 'nfl:ALL'
        # channel: str = 'accountabletech'
        # channel: str = 'PolyMatter:ALL'
        # channel: str = 'HistoryMatters'
        # channel: str = 'thedealguy'
        # os.environ[YouTube.ENVIRON_CHANNEL] = f'{channel}:ALL'
        os.environ[YouTube.ENVIRON_CHANNEL] = f'{channel}'
        yt = YouTube()

        channel_data_class: SchemaDataItem = \
            data_classes[YouTubeChannel.DATASTORE_CLASS_NAME]

        ingested_channels: set[str] = await YouTube.load_ingested_channels(
            member.member_id, channel_data_class, data_store
        )
        self.assertEqual(len(ingested_channels), 0)
        ingested_channels = None
        ingested_videos: dict[str, dict[str, str]] = \
            await YouTube.load_ingested_videos(
                member.member_id, data_class, data_store
            )
        self.assertEqual(len(ingested_videos), 0)
        ingested_videos = None

        data_class: SchemaDataItem = \
            data_classes[YouTubeVideo.DATASTORE_CLASS_NAME]
        video_table: Table = data_store.get_table(
            member.member_id, data_class.name
        )
        await video_table.append(
            {
                'publisher_asset_id': '2BqKA3DO',
                'created_timestamp': datetime.now(tz=UTC),
                'title': 'test video 1',
                'channel': 'test case',
                'asset_id': uuid4(),
                'asset_type': 'video',
                'ingest_status': IngestStatus.PUBLISHED,
            },
            cursor='1234567',
            origin_id=uuid4(),
            origin_id_type=IdType.MEMBER,
            origin_class_name='public_assets',
        )
        await video_table.append(
            {
                'publisher_asset_id': 'OD08BC26QaM',
                'created_timestamp': datetime.now(tz=UTC),
                'title': 'test video 2',
                'channel': 'test case',
                'asset_id': uuid4(),
                'asset_type': 'video',
                'ingest_status': IngestStatus.EXTERNAL,
            },
            cursor='1234567',
            origin_id=uuid4(),
            origin_id_type=IdType.MEMBER,
            origin_class_name='public_assets',
        )

        channel_name: str = channel
        if ':' in channel_name:
            channel_name = channel_name.split(':', maxsplit=1)[0]
        jwt: JWT = JWT.create(
            member.member_id, IdType.MEMBER, member.data_secret, network.name,
            BYOTUBE_SERVICE_ID, IdType.APP, MODTEST_APP_ID,
            expiration_seconds=3 * 24 * 60 * 60
        )
        mod_url: str = f'https://{MODTEST_FQDN}'
        mod_api_url: str = mod_url + YouTube.MODERATION_REQUEST_API
        mod_claim_url: str = mod_url + YouTube.MODERATION_CLAIM_URL

        await yt.import_videos(
            member, data_store, video_table, storage_driver,
            ingested_channels,
            moderate_request_url=mod_api_url,
            moderate_jwt_header=jwt.encoded,
            moderate_claim_url=mod_claim_url,
            ingest_interval=4,
            custom_domain='test_domain'
        )

        ingested_videos = await YouTube.load_ingested_videos(
            member.member_id, data_class, data_store
        )
        self.assertGreaterEqual(len(ingested_videos), 1)

        await yt.import_videos(
            member, data_store, video_table, storage_driver,
            ingested_channels,
            moderate_request_url=mod_api_url,
            moderate_jwt_header=jwt.encoded,
            moderate_claim_url=mod_claim_url,
            ingest_interval=4,
            custom_domain='test_domain'
        )

        newly_ingested_videos: dict[str, dict[str, str]] = \
            await YouTube.load_ingested_videos(
                member.member_id, data_class, data_store
            )
        self.assertEqual(len(ingested_videos), len(newly_ingested_videos))

        ingested_channels = await YouTube.load_ingested_channels(
            member.member_id, channel_data_class, data_store
        )
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
        data: dict[str, list[dict[str, dict[str, any]]]] = resp.json()
        self.assertGreaterEqual(len(data), 2)
        self.assertEqual(len(data['edges'][0]['node']['claims']), 0)

        # Start with clean slate
        yt = YouTube()

        await yt.import_videos(
            member, data_store, video_table, storage_driver,
            ingested_channels, ingest_interval=4,
            custom_domain=server.custom_domain
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
