#!/usr/bin/env python3

import os
import sys
import unittest

from byoda.data_import.youtube import YouTube
from byoda.data_import.youtube_video import YouTubeVideo
from byoda.data_import.youtube_channel import YouTubeChannel

from byoda.util.logger import Logger

_LOGGER = None

API_KEY_FILE: str = 'tests/collateral/local/youtube-data-api.key'


class TestFileStorage(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        os.environ[YouTube.ENVIRON_CHANNEL] = ''
        os.environ[YouTube.ENVIRON_API_KEY] = ''

    async def test_scrape_videos(self) -> None:

        ytv = YouTubeVideo()
        await ytv.scrape(
            video_id='RQm5lGne5_0', ingest_videos=False,
            creator_thumbnail=None,
        )
        self.assertequal(ytv.publisher, 'YouTube')

    async def test_scrape_creator(self) -> None:
        channel: str = 'History Matters'
        ytc = YouTubeChannel(name=channel)
        await ytc.scrape(
            filename='tests/collateral/yt-channel.html'
        )
        self.assertGreater(len(ytc.videos), 33)

    async def test_import_videos(self) -> None:
        return
        with open(API_KEY_FILE, 'r') as file_desc:
            api_key: str = file_desc.read().strip()

        os.environ[YouTube.ENVIRON_API_KEY] = api_key
        os.environ[YouTube.ENVIRON_CHANNEL] = 'Dathes'
        yt = YouTube()
        await yt.get_videos(max_api_requests=250)

    async def test_external_url_parsing(self) -> None:
        urls: dict[str, str] = {
            'https://www.youtube.com/watch?v=TwHn-O_GeSg': 'YouTube',
            'https://www.linkedin.com/in/satyanadella/': 'LinkedIn',
            'https://twitter.com/elonmusk': 'Twitter',
            'https://www.facebook.com/zuck': 'Facebook',
            'https://www.instagram.com/zuck/': 'Instagram',
            'https://dathes.byoda.me': 'www'
        }

        for url, expected in urls.items():
            result: str = YouTubeChannel._generate_external_link(
                {'content': url}, 10
            )
            self.assertEqual(result['name'], expected)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
