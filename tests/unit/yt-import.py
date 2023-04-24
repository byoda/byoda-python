#!/usr/bin/env python3

import os
import sys
import unittest

from byoda.data_import.youtube import YouTube

from byoda.util.logger import Logger

_LOGGER = None

TEST_FILE: str = 'tests/collateral/yt-channel-videos.html'

API_KEY_FILE: str = 'tests/collateral/local/youtube-data-api.key'


class TestFileStorage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ[YouTube.ENVIRON_CHANNEL] = ''
        os.environ[YouTube.ENVIRON_API_KEY] = ''

    async def test_scrape_videos(self):
        os.environ[YouTube.ENVIRON_CHANNEL] = 'besmart'

        yt = YouTube()
        await yt.get_videos('tests/collateral/yt-import.html')
        self.assertEqual(len(yt.videos), 115)

    async def test_import_videos(self):
        with open(API_KEY_FILE, 'r') as file_desc:
            api_key = file_desc.read().strip()

        os.environ[YouTube.ENVIRON_API_KEY] = api_key
        yt = YouTube()
        await yt.get_videos()


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()

