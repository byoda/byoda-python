#!/usr/bin/env python3

import os
import sys
import unittest

from logging import Logger

from byoda.data_import.youtube import YouTube
from byoda.data_import.youtube_video import YouTubeVideo
from byoda.data_import.youtube_channel import YouTubeChannel

from byoda.util.logger import Logger as ByodaLogger


_LOGGER = None

API_KEY_FILE: str = 'tests/collateral/local/youtube-data-api.key'


class TestYouTubeScrape(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        os.environ[YouTube.ENVIRON_CHANNEL] = ''
        os.environ[YouTube.ENVIRON_API_KEY] = ''

    async def test_scrape_videos(self) -> None:
        ytv = YouTubeVideo()
        await ytv.scrape(
            video_id='RQm5lGne5_0', ingest_videos=False,
            channel_name='test', creator_thumbnail=None,
        )
        self.assertEqual(ytv.publisher, 'YouTube')

    async def test_channel_data(self) -> None:
        '''
        Tests that all data needed is scraped from the channel page
        '''

        channel: str = 'History Matters'
        ytc = YouTubeChannel(name=channel)
        page_data: str = await ytc.get_videos_page()
        ytc.parse_channel_info(page_data)
        self.assertEqual(ytc.channel_id, 'UC22BdTgxefuvUivrjesETjg')
        self.assertEqual(len(ytc.channel_thumbnails), 3)
        self.assertTrue(
            ytc.description.startswith('History Matters is a history-focused')
        )
        self.assertEqual(ytc.name, 'History Matters')
        self.assertEqual(ytc.title, 'History Matters')
        self.assertEqual(len(ytc.videos), 0)
        self.assertEqual(len(ytc.external_urls), 2)

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
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )

    unittest.main()
