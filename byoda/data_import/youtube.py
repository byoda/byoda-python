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
import asyncio
import logging

from enum import Enum
from uuid import UUID, uuid4
from datetime import datetime, timezone

from dateutil import parser

import orjson

from bs4 import BeautifulSoup

from googleapiclient.discovery import build
from googleapiclient.discovery import Resource as YouTubeResource

from byoda.datastore.data_store import DataStore

from byoda.util.api_client.api_client import ApiClient

from byoda import config

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

    def __str__(self) -> str:
        return f'{self.size}_{self.height}_{self.width}_{self.url}'

class YouTubeVideo:
    def __init__(self):
        self.video_id: str | None = None
        self.title: str | None = None
        self.long_title: str | None = None
        self.description: str | None = None
        self.channel_creator: str | None = None
        self.published_time: datetime | None = None
        self.published_time_info: str | None = None
        self.view_count: str | None = None
        self.url: str | None = None
        self.thumbnails: dict[YouTubeThumbnail] = {}

        self.publisher = 'YouTube'
        self.asset_type: str = 'video'
        self.asset_id: UUID = uuid4()
        self.locale: str | None = None
        self.annotations: list[str] = []


        self.created_time: datetime = datetime.now(tz=timezone.utc)

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
        video.url: str = f'https://www.youtube.com/watch?v={video.video_id}'

        snippet = data.get('snippet')
        if not 'snippet':
            raise ValueError('Invalid data from YouTube API: no snippet')

        video.published_time: datetime = parser.parse(
            snippet['publishedAt']
        )
        video.channel_id: str = snippet['channelId']
        video.channel_creator: str = snippet['channelTitle']
        video.title: str = snippet['title']
        video.description: str = snippet['description']
        video.is_live_broadcast = snippet['liveBroadcastContent']

        thumbnails = snippet.get('thumbnails', {})

        for size, thumbnail in thumbnails.items():
            video.thumbnails[size] = YouTubeThumbnail(size, thumbnail)

        return video

    def to_datastore(self, member_id: UUID, data_store: DataStore) -> bool:
        '''
        Adds a video to the datastore, if it does not exist already

        :param member_id: The member ID
        :param data_store: The data store to store the videos in
        :returns: True if the video was added, False if it already existed
        '''

        if bool(member_id) != bool(data_store):
            raise ValueError(
                'Either both or neither member_id and data_store must be specified'
            )

        filterset = {
            'published_asset_id': {
                'eq': self.video_id,
            }
        }

        data = data_store.query(
            member_id, YouTube.DATASTORE_CLASS_NAME,
            filterset=filterset
        )
        if len(data):
            _LOGGER.debug(
                f'YouTube video {self.video_id} is already in the BYODA membership'
            )
            return False

        asset = {}
        for field, mapping in YouTube.DATASTORE_FIELD_MAPPINGS.items():
            value = getattr(self, field)
            if value:
                asset[mapping] = value

            asset['thumbnails'] = [
                str(thumbnail) for thumbnail in self.thumbnails
            ]

        data_store.append(member_id, YouTube.DATASTORE_CLASS_NAME, asset)

class YouTubeChannel:
    def __init__(self, name: str = None, channel_id: str = None,
                 api_client: YouTubeResource = None):
        self.name: str = name
        self.channel_id: str | None = channel_id
        self.api_client: YouTubeResource | None = api_client

        self.videos: dict[YouTubeVideo] = {}

    async def scrape(self, member_id: UUID = None, data_store: DataStore = None,
                     filename: str = None):
        '''
        Scrapes videos from the YouTube website and optionally stores them in
        the data store

        '''

        if bool(member_id) != bool(data_store):
            raise ValueError(
                'Either both or neither member_id and data_store must be specified'
            )

        if filename:
            with open(filename, 'r') as file_desc:
                data = file_desc.read()
        else:
            resp = await ApiClient.call(
                YouTube.CHANNEL_VIDEOS_URL.format(channel_id=self.name)
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

        # The strategy here is simple: we try to store all videos. to_datastore()
        # first checks whether the video is already in the data store and only adds it
        # if it is not.
        if data_store:
            for video in self.videos:
                video.to_datastore(member_id, data_store)

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

    async def import_videos(self, member_id: UUID = None,
                            data_store: DataStore = None,
                            max_api_requests: int = 100):
        '''
        Imports the videos from the YouTube data API. It processes the newest
        videos first and stops the import when it tries to import a video that
        already exists in the data store.

        TODO: reduce fragility against API call failures for older videos as
        the current logic would not try to import those because newer videos
        were already ingested
        '''

        if bool(member_id) != bool(data_store):
            raise ValueError(
                'Either both or neither member_id and data_store must be specified'
            )

        if not self.channel_id:
            self.get_channel_id()

        page_token = None
        api_requests = 0
        retries: int = 0
        max_retries: int = 3
        retry_delay: list[int] = [0, 10, 180, 1800]
        while True:
            delay = retry_delay[retries]
            if delay:
                _LOGGER.debug(f'Retry {retries}, delaying {delay} seconds')
                asyncio.sleep(retry_delay[retries])

            try:
                request = self.api_client.search().list(
                    order='date',
                    pageToken=page_token,
                    part="id, snippet",
                    type='video',
                    channelId=self.channel_id,
                    maxResults=50
                )
                response = request.execute()
                retries = 0
            except Exception as exc:
                retries += 1
                _LOGGER.debug(f'YouTube Data API call failed, try {retries}: {exc}')

            page_token: str = response.get('nextPageToken')
            api_requests += 1

            duplicate_video_found = self._import_video_data(
                response.get('items', []), member_id, data_store
            )

            if not duplicate_video_found:
                self.api_client.close()
                return

            if not page_token:
                self.api_client.close()
                _LOGGER.debug(
                    f'Empty page token, ending import after {len(self.videos)} videos '
                    f'for channel {self.channel_name}'
                )
                return

            if api_requests >= max_api_requests:
                self.api_client.close()
                _LOGGER.debug(
                    f'Max of {max_api_requests} API requests reached '
                    f'for channel {self.channel_name}, ending import '
                )
                return

            if retries > max_retries:
                self.api_client.close()
                _LOGGER.info(
                    f'Max retries exceeded, ending import after {len(self.videos)} videos '
                    f'for channel {self.channel_name}'
                )
                return

    def _import_video_data(self, data: dict, member_id: UUID = None,
                           data_store: DataStore = None) -> bool:
        '''
        Parse the data returned by the YouTube Data Search API and import the
        data to the data store

        :param data: the 'items' data as returned by the YouTube Data Search API
        :param member_id: the member ID of the pod for the service
        :param data_store: the data store to import the data to
        :returns: whether a duplicate video ID was encountered
        '''

        if bool(member_id) != bool(data_store):
            raise ValueError(
                'Either both or neither member_id and data_store must be specified'
            )

        for video_data in data:
            video = YouTubeVideo.from_api(video_data)
            self.videos[video.video_id] = video

            result = None
            if data_store:
                result = video.to_datastore(member_id, data_store)
                if not result:
                    _LOGGER.debug(
                        f'Found duplicate video ID {video.video_id}, '
                        f'ending import for channel {self.channel_name}'
                    )
                    return True

        return False

class YouTube:
    ENVIRON_CHANNEL: str = 'YOUTUBE_CHANNEL'
    ENVIRON_API_KEY: str = 'YOUTUBE_API_KEY'
    SCRAPE_URL: str = 'https://www.youtube.com'
    CHANNEL_URL: str = SCRAPE_URL + '/channel/{channel_id}'
    CHANNEL_VIDEOS_URL: str = SCRAPE_URL + '/channel/{channel_id}/videos'
    CHANNEL_SCRAPE_REGEX = re.compile(r'var ytInitialData = (.*?);')
    DATASTORE_CLASS_NAME: str = 'public_assets'
    DATASTORE_FIELD_MAPPINGS: dict[str, str] = {
        'video_id': 'publisher_asset_id',
        'title': 'title',
        'description': 'contents',
        'published_time': 'published_timestamp',
        'url': 'asset_url',
        'channel_creator': 'creator',
        'url': 'asset_url',
        'created_time': 'created_timestamp',
        'asset_type': 'asset_type',
        'asset_id': 'asset_id',
        'locale': 'locale',
        'publisher': 'publisher'
    }

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

    async def scrape_videos(self, member_id: UUID = None, data_store: DataStore = None,
                            filename: str = None) -> None:
        '''
        Scrape videos from the YouTube website

        :param filename: only used for unit testing
        '''

        if bool(member_id) != bool(data_store):
            raise ValueError(
                'Either both or neither member_id and data_store must be specified'
            )

        for channel in self.channels.values():
            await channel.scrape(member_id, data_store, filename=filename)

    async def import_videos(self, member_id: UUID = None, data_store: DataStore = None,
                            max_requests: int = 100) -> None:
        '''
        Import the videos from the YouTube channel
        '''

        if bool(member_id) != bool(data_store):
            raise ValueError(
                'Either both or neither member_id and data_store must be specified'
            )

        for channel in self.channels.values():
            await channel.import_videos(member_id, data_store, max_requests)

    async def get_videos(self, member_id: UUID = None, data_store: DataStore = None,
                         max_requests: int = 100, filename: str = None):
        '''
        Get videos from YouTube, either using scraping or the YouTube data API.

        The environment variable 'YOUTUBE_CHANNEL' is used to select the
        channel(s) to scrape from. Multiple channels can be specified by providing
        a comma-separated list of channel names.

        If the environment variable 'YOUTUBE_API_KEY' is set, the YouTube data API
        is called to import the videos. Otherwise, the YouTube website is scraped

        :param member_id: the member ID to use for the membership of the pod of
        the service
        :param data_store: The data store to use for storing the videos
        :param max_requests: maximimum number of YouTube data API requests to send.
        Each 'search' API call consumes 100 tokens out of the default limit of
        YouTube for 10k tokens. The max_requests is per channel, so if there are
        multiple channels, you should specify a fraction of 100 requests. This
        parameter is only used for import using the YouTube data API, not for
        when scraping the YouTube website.
        :param filename: scrape content from a file instead of the website, only
        supported for scraping, not for importing using the YouTube data API
        '''

        if bool(member_id) != bool(data_store):
            raise ValueError(
                'Either both or neither member_id and data_store must be specified'
            )

        if not self.integration_enabled:
            _LOGGER.info('YouTube integration is enabled')

        if not self.youtube_api_integration_enabled():
            await self.scrape_videos(filename=filename)
            return

        if filename:
            raise ValueError('Importing from a file is not supported')

        await self.import_videos(member_id, data_store, max_requests)

