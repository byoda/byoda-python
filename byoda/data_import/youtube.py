'''
Import data from Youtube


Takes as input environment variables
YOUTUBE_CHANNEL_NAME

Instructions to set up YouTube Data API key:
https://medium.com/mcd-unison/youtube-data-api-v3-in-python-tutorial-with-examples-e829a25d2ebd

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import re
import logging

from enum import Enum
from datetime import datetime

from dateutil import parser

import orjson

from bs4 import BeautifulSoup

from googleapiclient.discovery import build
from googleapiclient.discovery import Resource as YouTubeResource

from byoda.util.api_client.api_client import ApiClient

_LOGGER = logging.getLogger(__name__)


class YouTubeAssetType(Enum):
    # flake8: noqa=E221
    VIDEO           = 'video'
    PLAYLIST        = 'playlist'
    CHANNEL         = 'channel'


class YouTubeThumbnailSize(Enum):
    # flake8: noqa=E221
    DEFAULT         = 'default'
    MEDIUM          = 'medium'
    HIGH            = 'high'


class YouTubeThumbnail:
    def __init__(self, size: str, data: dict):
        self.url: str = data['url']
        self.width: int = data['width']
        self.height: int = data['height']
        if size:
            self.size = YouTubeThumbnailSize(size)
        else:
            self.size = f'{self.width}x{self.height}'


class YouTubeVideo:
    def __init__(self):
        self.video_id: str | None = None
        self.title: str | None = None
        self.long_title: str | None = None
        self.description: str | None = None
        self.published_time: datetime | None = None
        self.published_time_info: str | None = None
        self.view_count: str | None = None
        self.url: str | None = None
        self.thumbnails: dict[YouTubeThumbnail] = {}

        # If this has a value then it is not a video but a
        # playlist
        self.playlistId: str | None = None

    @staticmethod
    def from_scrape(data):
        video = YouTubeVideo()
        video.video_id = data['videoId']

        title: dict = data.get('title')
        if title:
            video.title = title.get('simpleText', video.title)
            if not video.title:
                video.title = title['runs'][0]['text']

            video.long_title = \
                title['accessibility']['accessibilityData']['label']

        if 'description' in data:
            video.description = data['description']['runs'][0]['text']

        if 'thumbnail' in data:
            for thumbnail in data['thumbnail']['thumbnails']:
                thumbnail = YouTubeThumbnail(None, thumbnail)
                video.thumbnails[thumbnail.size] = thumbnail

        if 'publishedTimeText' in data:
            time = data['publishedTimeText']
            if 'simpleText' in time:
                video.published_time_info: str = time['simpleText']

            if not video.published_time_info:
                video.published_time = time['runs'][0]['text']

        if 'viewCountText' in data:
            video.view_count = data['viewCountText']['simpleText']

        video.url: str = None
        nav_endpoint = data.get('navigationEndpoint')
        if nav_endpoint:
            command_metadata = nav_endpoint['commandMetadata']
            path = command_metadata['webCommandMetadata']['url']
            video.url = f'https://www.youtube.com/{path}'

        video.playlist_id = data.get('playlistId')

        return video

    @staticmethod
    def from_api(data):
        '''
        Collects the data from the YouTube data API
        '''

        video = YouTubeVideo()

        if 'id' not in data:
            raise ValueError('Invalid data from YouTube API: no id')

        video.kind: str = data['id']['kind']
        video.video_id: str = data['id']['videoId']

        snippet = data.get('snippet')
        if not 'snippet':
            raise ValueError('Invalid data from YouTube API: no snippet')

        video.published_time: datetime = parser.parse(
            snippet['publishedAt']
        )
        video.channel_id: str = snippet['channelId']
        video.title: str = snippet['title']
        video.description: snippet['description']
        video.is_live_broadcast = snippet['liveBroadcastContent']

        thumbnails = snippet.get('thumbnails', {})

        for size, thumbnail in thumbnails.items():
            video.thumbnails[size] = YouTubeThumbnail(size, thumbnail)


class YouTubeChannel:
    def __init__(self, name: str = None, channel_id: str = None,
                 api_client: YouTubeResource = None):
        self.name: str = name
        self.channel_id: str | None = channel_id
        self.api_client: YouTubeResource | None = api_client

        self.videos: dict[YouTubeVideo] = {}

    async def scrape(self, filename: str = None):
        if filename:
            with open(filename, 'r') as file_desc:
                data = file_desc.read()
        else:
            resp = await ApiClient.call(
                YouTube.CHANNEL_VIDEOS_URL.format(self.name)
            )

            data = await resp.text()

        soup = BeautifulSoup(data, 'html.parser')
        script = soup.find('script', string=YouTube.CHANNEL_SCRAPE_REGEX)

        raw_data = YouTube.CHANNEL_SCRAPE_REGEX.search(
            script.text
        ).group(1)

        data = orjson.loads(raw_data)

        self.find_videos(data, self.videos)

        _LOGGER.debug(
            f'Scraped {len(self.videos)} videos from '
            f'YouTube channel {self.name}'
        )

    def find_videos(self, data: dict | list | int | str | float,
                    titles: dict[str, YouTubeVideo]) -> None:
        '''
        Find the videos in the by walking through the deserialized
        output of a YouTube scrape
        '''

        if isinstance(data, list):
            for item in data:
                if type(item) in (dict, list):
                    self.find_videos(item, titles)
        elif isinstance(data, dict):
            video_id = data.get('videoId')
            if video_id:
                if video_id not in self.videos:
                    self.videos[video_id] = YouTubeVideo.from_scrape(data)

                return

            for value in data.values():
                if type(value) in (dict, list):
                    self.find_videos(value, titles)

    def get_channel_id(self):
        '''
        Gets the channel ID using the YouTube data search API
        '''

        if not self.api_client:
            raise RuntimeError(
                'instance not set up for calling YouTube data API'
            )

        request = self.api_client.search().list(
            q=self.name,
            part='id, snippet',
            maxResults=5,
            type='channel'
        )
        response = request.execute()
        if 'items' not in response:
            raise ValueError(f'Channel {self.name} not found')

        self.channel_id = response['items'][0]['id']['channelId']

    async def import_videos(self):
        if not self.channel_id:
            self.get_channel_id()

        page_token = None
        while True:
            request = self.api_client.search().list(
                    order='date',
                    pageToken=page_token,
                    part="id, snippet",
                    type='video',
                    channelId=self.channel_id,
                    maxResults=50
            )

            response = request.execute()
            for video_data in response.get('items', []):
                video = YouTubeVideo()
                video.from_api(video_data)
                self.videos[video.video_id] = video


class YouTube:
    ENVIRON_CHANNEL: str = 'YOUTUBE_CHANNEL'
    ENVIRON_API_KEY: str = 'YOUTUBE_API_KEY'
    SCRAPE_URL = 'https://www.youtube.com'
    CHANNEL_URL = SCRAPE_URL + '/channel/{channel_id}'
    CHANNEL_VIDEOS_URL = SCRAPE_URL + '/channel/{channel_id}/videos'
    CHANNEL_SCRAPE_REGEX = re.compile(r'var ytInitialData = (.*?);')

    def __init__(self, api_key: str | None = None):
        self.integration_enabled = YouTube.youtube_integration_enabled()
        self.api_enabled = YouTube.youtube_api_integration_enabled()

        self.api_client: YouTubeResource | None = None

        self.api_key: str | None = api_key
        if not self.api_key:
            self.api_key = os.environ.get(YouTube.ENVIRON_API_KEY)

        if self.api_key:
            self.api_client = build('youtube', 'v3', developerKey=self.api_key)

        self.channels: dict[str, YouTubeChannel] = {
            name: YouTubeChannel(name, api_client=self.api_client) for name in
            os.environ.get(YouTube.ENVIRON_CHANNEL).split(',')
        }

    @staticmethod
    def youtube_integration_enabled() -> bool:
        return os.environ.get(YouTube.ENVIRON_CHANNEL) is not None

    @staticmethod
    def youtube_api_integration_enabled() -> bool:
        integration_enabled = YouTube.youtube_integration_enabled()
        api_enabled = os.environ.get(YouTube.ENVIRON_API_KEY)

        return integration_enabled and api_enabled

    async def scrape_videos(self, filename: str = None) -> None:
        '''
        Scrape videos from the YouTube website

        :param filename: only used for unit testing
        '''

        for channel in self.channels.values():
            await channel.scrape(filename)

    async def import_videos(self) -> None:
        '''
        Import the videos from the YouTube channel
        '''

        for channel in self.channels.values():
            await channel.import_videos()

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

        await self.import_videos()

