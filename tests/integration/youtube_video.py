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
from logging import Logger
from datetime import UTC
from datetime import datetime

import httpx

from yt_dlp import YoutubeDL

from byoda.data_import.youtube_client import Response
from byoda.data_import.youtube_channel import YouTubeChannel
from byoda.data_import.youtube_client import AsyncYouTubeClient
from byoda.data_import.youtube_thumbnail import YouTubeThumbnail

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

from byoda.util.fastapi import setup_api

from byoda.util.logger import Logger as ByodaLogger

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
from tests.lib.defines import BYOTUBE_LOCAL_SCHEMA
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

        mock_environment_vars(TEST_DIR, hash_password=False)
        network_data: dict[str, str] = await setup_network(
            delete_tmp_dir=False
        )

        config.test_case = 'TEST_CLIENT'
        config.disable_pubsub = True

        account: Account = await setup_account(
            network_data, test_dir=TEST_DIR, clean_pubsub=False,
            service_id=BYOTUBE_SERVICE_ID, version=2,
            local_service_contract=BYOTUBE_LOCAL_SCHEMA
        )

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        os.makedirs(
            f'{TEST_DIR}/network-byoda.net/services/service-16384',
            exist_ok=True
        )
        shutil.copy(
            BYOTUBE_LOCAL_SCHEMA,
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

    @unittest.skip(
        'Skipping consent cookies test, '
        'generating new cookies not worked yet'
    )
    async def test_consent_cookies(self) -> None:
        client = AsyncYouTubeClient()
        await client.get_consent_cookies()
        response: Response = httpx.get(
            'https://www.youtube.com/', headers=client.headers,
            cookies=client.cookies
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(    # NOSONAR (S5906)
            'consent.youtube.com' in response.text
        )

    async def test_video_ingest(self) -> None:
        '''
        Test the content categories
        '''

        account: Account = config.server.account
        service_id: int = BYOTUBE_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        schema: Schema = member.schema
        data_classes: dict[str, SchemaDataItem] = schema.data_classes

        server: PodServer = config.server

        data_class: SchemaDataItem = \
            data_classes[YouTubeVideo.DATASTORE_CLASS_NAME]
        data_store: DataStore = server.data_store
        video_table: Table = data_store.get_table(
            member.member_id, data_class.name
        )

        channel_name: str = 'Marques Brownlee'
        storage_driver: FileStorage = server.storage_driver
        ytc = YouTubeChannel(
            name=channel_name, ingest=True, storage_driver=storage_driver
        )
        browse_client: YoutubeDL = ytc._setup_yt_dlp(with_download=False)
        download_client: YoutubeDL = ytc._setup_yt_dlp(with_download=True)

        thumb = YouTubeThumbnail(
            size='high',
            data={
                'url': 'https://i.ytimg.com/vi/5Y9L5NBINV4/hqdefault.jpg?sqp=-oaymwE1CKgBEF5IVfKriqkDKAgBFQAAiEIYAXABwAEG8AEB-AH-CYAC0AWKAgwIABABGGUgTyg_MA8=&rs=AOn4CLAXVLUryrnVlr6FnuChsr72CnCcFQ',   # noqa: E501
                'width': 480,
                'height': 360
            }
        )
        video: YouTubeVideo = await YouTubeVideo.scrape(
            'dtp6b76pMak', True, channel_name, thumb,
            consent_cookies=AsyncYouTubeClient.CONSENT_COOKIES,
            browse_client=browse_client, download_client=download_client,
            storage_driver=storage_driver
        )
        result: bool | None = await video.persist(
            member=member, ingest_asset=True,
            video_table=video_table, bento4_directory=BENTO4_DIRECTORY,
            moderate_request_url=None, moderate_jwt_header=None,
            moderate_claim_url=None, custom_domain=None,
            #_test_asset_dir=TEST_ASSET_DIR

        )
        self.assertIsNotNone(result)

    async def test_scrape_videos(self) -> None:
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

        # channel: str = 'Dathes'
        # channel: str = 'CNN'
        # channel: str = 'nfl:ALL'
        channel: str = 'accountabletech'
        # channel: str = 'PolyMatter:ALL'
        # channel: str = 'HistoryMatters'
        # channel: str = 'thedealguy'
        # os.environ[YouTube.ENVIRON_CHANNEL] = f'{channel}:ALL'
        os.environ[YouTube.ENVIRON_CHANNEL] = f'{channel}'

        yt = YouTube(storage_driver=storage_driver)

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
            member, data_store, video_table,
            moderate_request_url=mod_api_url,
            moderate_jwt_header=jwt.encoded,
            moderate_claim_url=mod_claim_url,
            ingest_interval=4,
            custom_domain='test_domain',
            max_videos=1
        )

        ingested_videos = await YouTube.load_ingested_videos(
            member.member_id, data_class, data_store
        )
        self.assertGreaterEqual(len(ingested_videos), 1)

        await yt.import_videos(
            member,
            data_store=data_store, video_table=video_table,
            bento4_directory=BENTO4_DIRECTORY,
            moderate_request_url=mod_api_url,
            moderate_jwt_header=jwt.encoded,
            moderate_claim_url=mod_claim_url,
            ingest_interval=4,
            custom_domain='test_domain',
            max_videos=1
        )

        newly_ingested_videos: dict[str, dict[str, str]] = \
            await YouTube.load_ingested_videos(
                member.member_id, data_class, data_store
            )
        self.assertGreaterEqual(
            len(newly_ingested_videos), len(ingested_videos)
        )

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
        yt = YouTube(storage_driver=storage_driver)

        await yt.import_videos(
            member, data_store, video_table,
            ingested_channels, ingest_interval=4,
            custom_domain=server.custom_domain
        )

    @unittest.skip('Boring...')
    async def test_scrape_unavailable_video(self) -> None:
        '''
        Test scraping a video that is unavailable
        '''

        ytc = YouTubeChannel(
            name='Marques Brownlee',
            storage_driver=config.server.storage_driver
        )
        browse_client: YoutubeDL = ytc._setup_yt_dlp(with_download=False)
        download_client: YoutubeDL = ytc._setup_yt_dlp(with_download=True)

        video_id: str = 'JZ9Qj7bGizA'
        video: YouTubeVideo = await YouTubeVideo.scrape(
            video_id, False, None, None,
            browse_client=browse_client, download_client=download_client,
            storage_driver=config.server.storage_driver

        )
        self.assertIsNotNone(video)
        self.assertIsNotNone(video.asset_id)
        self.assertEqual(video.ingest_status, IngestStatus.UNAVAILABLE)
        self.assertEqual(video.video_id, video_id)


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )
    unittest.main()
