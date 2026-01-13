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

from logging import Logger
from datetime import datetime

import httpx

from byoda.data_import.youtube_channel import YouTubeChannel
from byoda.data_import.youtube_client import AsyncYouTubeClient
from byoda.data_import.youtube_client import Response

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.dataclass import SchemaDataItem
from byoda.datamodel.table import Table


from byoda.datastore.data_store import DataStore

from byoda.data_import.youtube import YouTube
from byoda.data_import.youtube_video import YouTubeVideo

from byoda.util.api_client.api_client import ApiClient

from byoda.servers.pod_server import PodServer


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

from tests.lib.defines import BYOTUBE_SERVICE_ID
from tests.lib.defines import BYOTUBE_LOCAL_SCHEMA

_LOGGER = None

TEST_DIR = '/tmp/byoda-tests/yt-channel-import'

BENTO4_DIRECTORY: str = '../bento4'

HISTORY_MATTERS_CHANNEL: str = 'History Matters'


class TestYouTubeChannel(unittest.IsolatedAsyncioTestCase):
    '''
    Tests for downloading channel metadata from YouTube
    '''

    async def asyncSetUp(self) -> None:
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

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

    @unittest.skip('Getting new consent cookies has never worked')
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
        self.assertIn('CONSENT', response.cookies.jar)

    async def test_channel_scrape_history_matters(self) -> None:
        '''
        Tests that all data needed is scraped from the channel page
        '''

        account: Account = config.server.account
        service_id: int = BYOTUBE_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        ytc: YouTubeChannel = YouTubeChannel(
            name=HISTORY_MATTERS_CHANNEL,
            storage_driver=config.server.storage_driver
        )
        await ytc.scrape()
        self.assertEqual(ytc.youtube_channel_id, 'UC22BdTgxefuvUivrjesETjg')
        self.assertEqual(len(ytc.channel_thumbnails), 1)
        self.assertTrue(
            ytc.description.startswith('History Matters is a history-focused')
        )
        self.assertEqual(ytc.name, HISTORY_MATTERS_CHANNEL)
        self.assertEqual(ytc.title, HISTORY_MATTERS_CHANNEL)
        self.assertEqual(len(ytc.keywords), 1)
        self.assertIn('Education', ytc.keywords)
        self.assertEqual(len(ytc.videos), 0)
        self.assertGreaterEqual(len(ytc.external_urls), 2)
        # this banners test is flakey as scrape does not always include
        # expected 'c4TabbedHeaderRenderer' in the page_data
        # self.assertEqual(len(ytc.banners), 16)

        page_data: str = await ytc.get_videos_page()
        ytc.parse_channel_video_data(page_data)
        self.assertEqual(ytc.channel_thumbnail.size, '72x72')
        video_ids: set[str] = await ytc.get_video_ids()
        self.assertGreaterEqual(len(video_ids), 300)
        self.assertIn('nVFqq1a1r_s', video_ids)

        await ytc.persist_channel_info_media(
            member, config.server.data_store
        )

    async def test_channel_parsing_cnn(self) -> None:
        '''
        Test getting the channel from a video
        '''

        channel_name: str = 'CNN'
        ytc: YouTubeChannel = YouTubeChannel(
            name=channel_name, storage_driver=config.server.storage_driver
        )

        await ytc.scrape()
        self.assertEqual(ytc.youtube_channel_id, 'UCupvZG-5ko_eiXAupbDfxWw')
        self.assertEqual(ytc.title, channel_name)
        self.assertEqual(ytc.country, 'United States')
        self.assertIn(
            'CNN is the world leader in news and information',
            ytc.description
        )
        self.assertTrue(ytc.verified)
        self.assertGreaterEqual(ytc.view_count, 19584510525)
        self.assertGreaterEqual(ytc.subscriber_count, 19000000)
        self.assertGreaterEqual(ytc.video_count, 178818)
        self.assertEqual(ytc.joined_date, datetime(2005, 10, 2))

        self.assertEqual(len(ytc.channel_thumbnails), 1)
        self.assertIsNotNone(ytc.channel_thumbnail)
        self.assertEqual(ytc.channel_thumbnail.size, '900x900')
        self.assertGreaterEqual(len(ytc.keywords), 30)
        self.assertEqual(ytc.country, 'United States')
        self.assertGreater(len(ytc.available_country_codes), 50)
        self.assertIn('US', ytc.available_country_codes)
        self.assertFalse(ytc.is_family_safe)
        self.assertGreaterEqual(len(ytc.external_urls), 5)

    async def test_channel_scrape_legal_eagle(self) -> None:
        '''
        Test getting the channel name from a video
        '''
        channel_name: str = 'LegalEagle'
        ytc: YouTubeChannel = YouTubeChannel(
            name=channel_name, storage_driver=config.server.storage_driver
        )
        await ytc.scrape()
        self.assertIsNotNone(ytc)
        self.assertEqual(ytc.title, channel_name)
        self.assertEqual(ytc.youtube_channel_id, 'UCpa-Zb0ZcQjTCPP1Dx_1M8Q')
        self.assertGreaterEqual(len(ytc.banners), 5)
        self.assertEqual(ytc.channel_thumbnail.size, '900x900')
        self.assertEqual(len(ytc.channel_thumbnails), 1)
        self.assertTrue(
            ytc.description.startswith(
                'Do you want to know how our legal system works?'
            )
        )
        self.assertGreaterEqual(len(ytc.external_urls), 7)
        self.assertGreaterEqual(len(ytc.keywords), 25)
        self.assertIn('trial', ytc.keywords)

    async def test_scrape_channel(self) -> None:
        account: Account = config.server.account
        service_id: int = BYOTUBE_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        schema: Schema = member.schema
        data_classes: dict[str, SchemaDataItem] = schema.data_classes
        class_name: str = YouTubeVideo.DATASTORE_CLASS_NAME
        data_class: SchemaDataItem = data_classes[class_name]

        server: PodServer = config.server
        data_store: DataStore = server.data_store

        video_table: Table = data_store.get_table(
            member.member_id, data_class.name
        )

        channel: YouTubeChannel = YouTubeChannel(
            'Dathes', storage_driver=config.server.storage_driver
        )
        await channel.scrape()
        await channel.scrape_videos(
            member, data_store, video_table,
            bento4_directory=BENTO4_DIRECTORY,
            moderate_request_url=None,
            moderate_jwt_header=None,
            moderate_claim_url=None,
            ingest_interval=1,
            custom_domain='test.byoda.me',
            max_videos_per_channel=10,
        )


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )
    unittest.main()
