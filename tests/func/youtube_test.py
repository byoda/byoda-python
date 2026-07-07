#!/usr/bin/env python3

import os
import sys
import shutil
import unittest

from logging import Logger

from yt_dlp import YoutubeDL

from byoda.storage.filestorage import FileStorage

from byoda.data_import.youtube import YouTube
from byoda.data_import.youtube_video import YouTubeVideo
from byoda.data_import.youtube_channel import YouTubeChannel
from byoda.data_import.youtube_channel import YouTubeExternalLink
from byoda.data_import.youtube_thumbnail import YouTubeThumbnail

from byoda.util.logger import Logger as ByodaLogger


_LOGGER = None

API_KEY_FILE: str = 'tests/collateral/local/youtube-data-api.key'

TEST_DIR: str = '/tmp/byoda-tests/youtube-scrape'


class TestYouTubeScrape(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        os.environ[YouTube.ENVIRON_CHANNEL] = ''
        os.environ[YouTube.ENVIRON_API_KEY] = ''
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.mkdir(TEST_DIR)

    async def test_metadata_scrape(self) -> None:
        thumb = YouTubeThumbnail(
            size='high',
            data={
                'url': 'https://dummy.youtube/thumbnail',
                'width': 480,
                'height': 360
            }
        )
        storage_driver: FileStorage = FileStorage(local_path=TEST_DIR)
        ytc = YouTubeChannel(
            name='Teletubbies - WildBrain', storage_driver=storage_driver
        )
        browse_client: YoutubeDL = ytc._setup_yt_dlp(with_download=False)
        download_client: YoutubeDL = ytc._setup_yt_dlp(with_download=True)

        ytv: YouTubeVideo = await YouTubeVideo.scrape(
            video_id='dQw4w9WgXcQ', ingest_videos=False,
            channel_name='Rick Astley', channel_thumbnail=thumb,
            browse_client=browse_client,
            download_client=download_client
        )
        self.assertEqual(
            ytv.title,
            'Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)'  # noqa: E501
        )
        self.assertEqual(ytv.channel, 'Rick Astley')
        self.assertEqual(ytv.video_id, 'dQw4w9WgXcQ')
        self.assertEqual(ytv.publisher, 'YouTube')
        self.assertTrue(ytv.is_family_safe)
        self.assertEqual(ytv.age_limit, 0)

    async def test_kids_video(self) -> None:
        thumb = YouTubeThumbnail(
            size='high',
            data={
                'url': 'https://dummy.youtube/thumbnail',
                'width': 480,
                'height': 360
            }
        )
        storage_driver: FileStorage = FileStorage(local_path=TEST_DIR)
        ytc = YouTubeChannel(
            name='Teletubbies - WildBrain', storage_driver=storage_driver
        )
        browse_client: YoutubeDL = ytc._setup_yt_dlp(with_download=False)
        download_client: YoutubeDL = ytc._setup_yt_dlp(with_download=True)
        ytv: YouTubeVideo = await YouTubeVideo.scrape(
            video_id='Kmp3eOXp780', ingest_videos=False,
            channel_name='Teletubbies - WildBrain',
            channel_thumbnail=thumb,
            browse_client=browse_client,
            download_client=download_client
        )
        self.assertTrue(ytv.is_family_safe)
        self.assertEqual(ytv.age_limit, 0)

    async def test_scrape_videos(self) -> None:
        thumb = YouTubeThumbnail(
            size='high',
            data={
                'url': 'https://dummy.youtube/thumbnail',
                'width': 480,
                'height': 360
            }
        )
        storage_driver: FileStorage = FileStorage(local_path=TEST_DIR)
        ytc = YouTubeChannel(
            name='Teletubbies - WildBrain', storage_driver=storage_driver
        )
        browse_client: YoutubeDL = ytc._setup_yt_dlp(with_download=False)
        download_client: YoutubeDL = ytc._setup_yt_dlp(with_download=True)
        ytv: YouTubeVideo = await YouTubeVideo.scrape(
            video_id='RQm5lGne5_0', ingest_videos=False,
            channel_name='GMHikaru', channel_thumbnail=thumb,
            browse_client=browse_client,
            download_client=download_client
        )
        self.assertEqual(ytv.publisher, 'YouTube')

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
            link: YouTubeExternalLink = YouTubeChannel._generate_external_link(
                url, 10
            )
            self.assertEqual(link.name, expected)


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )
    # inner()
    unittest.main()
