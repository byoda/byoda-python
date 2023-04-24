'''
Import data from Youtube


Takes as input environment variables
YOUTUBE_CHANNEL_NAME

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import re
import logging

import orjson
from bs4 import BeautifulSoup

from googleapiclient.discovery import build

from byoda.util.api_client.api_client import ApiClient

_LOGGER = logging.getLogger(__name__)


class YouTubeThumbnail:
    def __init__(self, data: dict):
        self.url: str = data['url']
        self.width: int = data['width']
        self.height: int = data['height']


class YouTubeVideo:
    def __init__(self):
        self.video_id: str | None = None
        self.title: str | None = None
        self.long_title: str | None = None
        self.description: str | None = None
        self.published_time: str | None = None
        self.view_count: str | None = None
        self.url: str | None = None
        self.thumbnails: list[YouTubeThumbnail] = []

        # If this has a value then it is not a video but a
        # playlist
        self.playlistId: str | None = None

    def update(self, data):
        self.video_id = data['videoId']

        title: dict = data.get('title')
        if title:
            self.title = title.get('simpleText', self.title)
            if not self.title:
                self.title = title['runs'][0]['text']

            self.long_title = \
                title['accessibility']['accessibilityData']['label']

        if 'description' in data:
            self.description = data['description']['runs'][0]['text']

        if 'thumbnail' in data:
            for thumbnail in data['thumbnail']['thumbnails']:
                self.thumbnails.append(YouTubeThumbnail(thumbnail))

        if 'publishedTimeText' in data:
            time = data['publishedTimeText']
            self.published_time = time.get('simpleText')

            if not self.published_time:
                self.published_time = time['runs'][0]['text']

        if 'viewCountText' in data:
            self.view_count = data['viewCountText']['simpleText']

        self.url: str = None
        nav_endpoint = data.get('navigationEndpoint')
        if nav_endpoint:
            command_metadata = nav_endpoint['commandMetadata']
            path = command_metadata['webCommandMetadata']['url']
            self.url = f'https://www.youtube.com/{path}'

        self.playlist_id = data.get('playlistId')


class YouTube:
    ENVIRON_CHANNEL: str = 'YOUTUBE_CHANNEL'
    ENVIRON_API_KEY: str = 'YOUTUBE_API_KEY'
    SCRAPE_URL = 'https://www.youtube.com'
    CHANNEL_URL = SCRAPE_URL + '/channel/{channel_id}'
    CHANNEL_VIDEOS_URL = SCRAPE_URL + '/channel/{channel_id}/videos'
    CHANNEL_SCRAPE_REGEX = re.compile(r'var ytInitialData = (.*?);')

    def __init__(self, api_key: str | None = None):
        self.channel_names: list[str] = os.environ.get(
            YouTube.ENVIRON_CHANNEL
        ).split(',')
        self.videos: dict[YouTubeVideo] = {}
        self.api_key: str | None = api_key
        self.integration_enabled = YouTube.youtube_integration_enabled()
        self.api_enabled = YouTube.youtube_api_integration_enabled()

    @staticmethod
    def youtube_integration_enabled() -> bool:
        return os.environ.get(YouTube.ENVIRON_CHANNEL) is not None

    @staticmethod
    def youtube_api_integration_enabled() -> bool:
        integration_enabled = YouTube.youtube_integration_enabled()
        api_enabled = os.environ.get(YouTube.ENVIRON_API_KEY) is not None

        return integration_enabled and api_enabled

    @staticmethod
    def find_videos(data: dict | list | int | str | float,
                    titles: dict[str, YouTubeVideo]) -> None:
        '''
        Find the videos in the output of a YouTube scrape
        '''
        if isinstance(data, list):
            for item in data:
                if type(item) in (dict, list):
                    YouTube.find_videos(item, titles)
        elif isinstance(data, dict):
            video_id = data.get('videoId')
            if video_id:
                if video_id not in titles:
                    titles[video_id] = YouTubeVideo()

                titles[video_id].update(data)
                return

            for value in data.values():
                if type(value) in (dict, list):
                    YouTube.find_videos(value, titles)

    async def scrape_videos(self, filename: str = None) -> None:
        '''
        Scrape videos from the YouTube website

        :param filename: only used for unit testing
        '''

        for channel_name in self.channel_names:
            channel_name = channel_name.lstrip('@')

            if filename:
                with open(filename, 'r') as file_desc:
                    data = file_desc.read()
            else:
                resp = await ApiClient.call(
                    YouTube.CHANNEL_VIDEOS_URL.format(channel_name)
                )

                data = await resp.text()

            soup = BeautifulSoup(data, 'html.parser')
            script = soup.find('script', string=YouTube.CHANNEL_SCRAPE_REGEX)

            raw_data = YouTube.CHANNEL_SCRAPE_REGEX.search(
                script.text
            ).group(1)

            data = orjson.loads(raw_data)

            YouTube.find_videos(data, self.videos)

            _LOGGER.debug(
                f'Scraped {len(self.videos)} videos from '
                f'YouTube channel {channel_name}'
            )

    async def import_videos(self) -> None:
        '''
        Import the videos from the YouTube channel
        '''

        raise NotImplementedError

    async def get_videos(self, filename: str = None):
        '''
        Get videos from YouTube

        :param filename: only used for unit testing
        '''

        if not self.integration_enabled:
            _LOGGER.info('YouTube integration is enabled')

        if not self.youtube_api_integration_enabled():
            await self.scrape_videos(filename)
            return

        videos: list[YouTubeVideo] = await self.import_videos()
        self.videos.update(videos)
