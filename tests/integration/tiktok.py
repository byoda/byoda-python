#!/usr/bin/env python3

raise NotImplementedError('This test is not yet implemented')
'''
WIP: this needs the pytok module to be installed
Test case for TikTok import of assets and their metadata

For importing video and audio tracks, BenTo4 needs to be installed
under /podserver/bento4: https://www.bento4.com/downloads/

'''

import os
import sys
import shutil
import asyncio
import unittest

from uuid import uuid4
from logging import Logger

from datetime import UTC
from datetime import datetime

from TikTokApi import TikTokApi

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

    async def test_tiktok(self) -> None:
        async with TikTokApi() as api:
            await api.create_sessions(ms_tokens=[None], num_sessions=1, sleep_after=3)
            async for video in api.trending.videos(count=30):
                print(video)
                print(video.as_dict)


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
