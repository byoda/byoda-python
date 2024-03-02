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

import httpx

import orjson

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


TEST_DIR: str = '/tmp/byoda-tests/assetdb'

TESTLIST: str = 'testlualist'

TEST_ASSET_ID: UUID = '32af2122-4bab-40bb-99cb-4f696da49e26'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        config_file: str = os.environ.get('CONFIG_FILE', 'config.yml')
        with open(config_file) as file_desc:
            app_config: dict[str, dict[str, any]] = yaml.safe_load(file_desc)

        config.debug = True

        app_config['appserver']['root_dir'] = TEST_DIR

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        if '192.168.' not in app_config['appserver']['asset_cache']:
            raise ValueError(
                'We must be a local Redis server for testing'
            )

        cache: SearchableCache = await SearchableCache.setup(
            app_config['appserver']['asset_cache']
        )
        config.cache = cache

        await cache.client.function_flush('SYNC')
        await cache.client.ft(cache.index_name).dropindex()
        await cache.client.delete(AssetCache.LIST_OF_LISTS_KEY)

        list_key: str = cache.get_list_key(TESTLIST)
        keys: list[str] = await cache.client.keys(f'{list_key}*')
        for key in keys:
            await cache.client.delete(key)

        keys: list[str] = await cache.client.keys(
            f'{SearchableCache.ASSET_KEY_PREFIX}*'
        )
        for key in keys:
            await cache.client.delete(key)

        await cache.client.aclose()

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        config.app = setup_api(
            'Byoda test svcserver', 'server for testing service APIs',
            'v0.0.1',
            [
                StatusRouter,
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        return

    @classmethod
    async def asyncTearDown(self) -> None:
        await ApiClient.close_all()

    async def test_service_data_api(self) -> None:
        BASE_URL: str = 'http://localhost:8000'
        AUTH_URL: str = f'{BASE_URL}/auth'

        async with httpx.AsyncClient(app=config.app) as client:
            resp: HttpResponse = await client.get(
                'http://localhost:8000/api/v1/status'
            )
            self.assertEqual(resp.status_code, 200)

            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/service/data?list_name={TESTLIST}'
            )
            self.assertEqual(resp.status_code, 200)


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
