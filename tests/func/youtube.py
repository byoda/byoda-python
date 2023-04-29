#!/usr/bin/env python3

import os
import sys
import shutil
import unittest

from byoda.datamodel.account import Account

from byoda.datastore.data_store import DataStore

from byoda.data_import.youtube import YouTube

from byoda.util.logger import Logger

from byoda import config

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

_LOGGER = None

TEST_DIR = '/tmp/byoda-tests/yt-import'
TEST_FILE: str = 'tests/collateral/yt-channel-videos.html'

API_KEY_FILE: str = 'tests/collateral/local/youtube-data-api.key'


class TestFileStorage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)

        config.test_case = 'TEST_CLIENT'

        config.server.account: Account = await setup_account(network_data)

        os.environ[YouTube.ENVIRON_CHANNEL] = ''
        os.environ[YouTube.ENVIRON_API_KEY] = ''

    @classmethod
    async def asyncTearDown(self):
        pass

    async def test_scrape_videos(self):
        account: Account = config.server.account
        await account.load_memberships()
        member = account.memberships.get(ADDRESSBOOK_SERVICE_ID)

        data_store: DataStore = config.server.data_store

        os.environ[YouTube.ENVIRON_CHANNEL] = 'besmart'

        yt = YouTube()
        await yt.get_videos(member.member_id, data_store)

        self.assertGreater(len(yt.channels['besmart'].videos), 50)

    async def test_import_videos(self):
        account: Account = config.server.account
        await account.load_memberships()
        member = account.memberships.get(ADDRESSBOOK_SERVICE_ID)

        data_store: DataStore = config.server.data_store

        with open(API_KEY_FILE, 'r') as file_desc:
            api_key = file_desc.read().strip()

        os.environ[YouTube.ENVIRON_API_KEY] = api_key
        os.environ[YouTube.ENVIRON_CHANNEL] = 'GMHikaru'
        yt = YouTube()
        await yt.get_videos(member.member_id, data_store, max_api_requests=3)


async def main():
    await setup_network(TEST_DIR)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
