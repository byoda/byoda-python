#!/usr/bin/env python3

import os
import sys
import unittest

import orjson

from byoda.datamodel.account import Account
from byoda.datamodel.network import Network

from byoda.datastore.data_store import DataStoreType

from byoda.data_import.youtube import YouTube

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from tests.lib.setup import setup_network
from tests.lib.setup import mock_environment_vars

_LOGGER = None

TEST_DIR = '/tmp/byoda-tests/podserver'
TEST_FILE: str = 'tests/collateral/yt-channel-videos.html'

API_KEY_FILE: str = 'tests/collateral/local/youtube-data-api.key'


class TestFileStorage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)

        config.test_case = 'TEST_CLIENT'

        network: Network = config.server.network
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        with open(f'{network_data["root_dir"]}/account_id', 'rb') as file_desc:
            network_data['account_id'] = orjson.loads(file_desc.read())

        account = Account(network_data['account_id'], network)
        account.password = network_data.get('account_secret')
        await account.load_secrets()

        server.account = account

        await config.server.set_data_store(
            DataStoreType.SQLITE, account.data_secret
        )

        await server.get_registered_services()

        app = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [account.tls_secret.common_name], [
                AccountRouter, MemberRouter, AuthTokenRouter,
                AccountDataRouter
            ]
        )

        for account_member in account.memberships.values():
            account_member.enable_graphql_api(app)

        os.environ[YouTube.ENVIRON_CHANNEL] = ''
        os.environ[YouTube.ENVIRON_API_KEY] = ''

    @classmethod
    async def asyncTearDown(self):
        pass

    async def test_scrape_videos(self):
        os.environ[YouTube.ENVIRON_CHANNEL] = 'besmart'

        yt = YouTube()
        await yt.get_videos()
        self.assertGreater(len(yt.channels['besmart'].videos), 100)

    async def test_import_videos(self):
        with open(API_KEY_FILE, 'r') as file_desc:
            api_key = file_desc.read().strip()

        os.environ[YouTube.ENVIRON_API_KEY] = api_key
        os.environ[YouTube.ENVIRON_CHANNEL] = 'GMHikaru'
        yt = YouTube()
        await yt.get_videos()


async def main():
    await setup_network(TEST_DIR)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
