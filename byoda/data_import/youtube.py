'''
Import data from Youtube


Takes as input environment variables
YOUTUBE_CHANNEL_NAME
YOUTUBE_API_KEY

This module supports two ways for ingesting YouTube videos:
- scraping the website. This is limited to the videos shown on the main page
of a channel. If the YouTube API key environment variable is not set then
this method will be used.
- Calling the YouTube Data API. This requires a YouTube Data API key. If the
YouTube API key environment variable is set then this method will be used.

Instructions to set up YouTube Data API key:
https://medium.com/mcd-unison/youtube-data-api-v3-in-python-tutorial-with-examples-e829a25d2ebd

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from uuid import UUID
from logging import getLogger

from googleapiclient.discovery import build
from googleapiclient.discovery import Resource as YouTubeResource

from byoda.datamodel.member import Member
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.dataclass import SchemaDataItem
from byoda.datamodel.table import QueryResult

from byoda.datastore.data_store import DataStore

from byoda.storage.filestorage import FileStorage

from byoda.util.logger import Logger

from .youtube_channel import YouTubeChannel

_LOGGER: Logger = getLogger(__name__)


class YouTube:
    ENVIRON_CHANNEL: str = 'YOUTUBE_CHANNEL'
    ENVIRON_API_KEY: str = 'YOUTUBE_API_KEY'
    MODERATION_REQUEST_API: str = '/api/v1/moderate/asset'
    MODERATION_CLAIM_URL: str = '/claims/{state}/{asset_id}.json'
    INGEST_INTERVAL_SECONDS: int = 60

    def __init__(self, api_key: str | None = None):
        '''
        Constructor. If the 'YOUTUBE_API_KEY environment variable is
        set then it will use that key to call the YouTube Data API. Otherwise
        it will scrape the YouTube website.
        '''
        self.integration_enabled = YouTube.youtube_integration_enabled()
        self.api_enabled = YouTube.youtube_api_integration_enabled()

        self.api_client: YouTubeResource | None = None

        self.api_key: str | None = api_key
        if not self.api_key:
            self.api_key = os.environ.get(YouTube.ENVIRON_API_KEY)

        if self.api_key:
            self.api_client = build('youtube', 'v3', developerKey=self.api_key)

        self.channels: dict[str, YouTubeChannel] = {}
        for name in os.environ.get(YouTube.ENVIRON_CHANNEL, '').split(','):
            ingest: bool = False
            if ':' in name:
                name, ingest = name.split(':')
                ingest = bool(ingest)

            channel = YouTubeChannel(
                name, ingest=ingest, api_client=self.api_client
            )
            self.channels[name] = channel

    @staticmethod
    def youtube_integration_enabled() -> bool:
        result = os.environ.get(YouTube.ENVIRON_CHANNEL) is not None

        _LOGGER.debug(f'YouTube integration enabled: {result}')

        return result

    @staticmethod
    def youtube_api_integration_enabled() -> bool:
        integration_enabled = YouTube.youtube_integration_enabled()
        api_enabled = os.environ.get(YouTube.ENVIRON_API_KEY)

        result = bool(integration_enabled and api_enabled)
        _LOGGER.debug(f'YouTube API integration enabled: {result}')
        return result

    @staticmethod
    async def load_ingested_videos(member_id: UUID, data_class: SchemaDataItem,
                                   data_store: DataStore
                                   ) -> dict[str, dict[str, str]]:
        '''
        Load the ingested assets from the data store

        :param member_id: the member ID to use for the membership of the pod of
        the service
        :param data_store: The data store to use for storing the videos
        :returns: a dictionary with the video ID as key and the encoding
        status as value
        '''

        filters = DataFilterSet(
            {
                'publisher': {
                    'eq': 'YouTube'
                }
            }
        )
        data: list[QueryResult] = await data_store.query(
            member_id, data_class, filters=filters
        )

        known_videos: dict[str, dict[str, str]] = {
            video_data['publisher_asset_id']: video_data
            for video_data, _ in data or []
        }

        _LOGGER.debug(f'Found {len(known_videos)} ingested videos')

        return known_videos

    async def persist_videos(self, member: Member,
                             storage_driver: FileStorage = None,
                             already_ingested_assets: dict[str, any] = {},
                             bento4_directory: str | None = None,
                             moderate_request_url: str | None = None,
                             moderate_jwt_header: str | None = None,
                             moderate_claim_url: str | None = None,
                             ingest_interval: int = INGEST_INTERVAL_SECONDS):
        '''
        Persist the videos to storage. Videos are stored in the data store.
        If ingest of videos is enabled for this channel then the videos are
        downloaded, otherwise only the metadata is stored.

        :param member:
        :param data_store:
        :param storage_driver: this parameter is required if we download the
        videos
        :param bento4_directory: this parameter is required if we download the
        assets and repackage them
        :param moderate_request_url: URL where to submit the request to review
        the moderation claim for thevideo
        :param moderate_jwt_header: JWT header to use for calling the
        moderation API
        :param moderate_claim_url:
        :param ingest_interval: interval in seconds between ingesting videos to
        avoid overloading YouTube API
        :param ValueError: if the storage driver is not specified and we ingest
        videos
        '''

        for channel in self.channels.values():
            if channel.ingest_videos and not storage_driver:
                raise ValueError(
                    'We need a storage driver to download videos '
                    f'for {channel.name}'
                )

            await channel.persist(
                member, storage_driver, already_ingested_assets,
                bento4_directory,
                moderate_request_url=moderate_request_url,
                moderate_jwt_header=moderate_jwt_header,
                moderate_claim_url=moderate_claim_url,
                ingest_interval=ingest_interval
            )

    async def scrape_videos(self,
                            already_ingested_videos: dict[str, dict] = {},
                            filename: str = None) -> None:
        '''
        Scrape videos from the YouTube website

        :param filename: only used for unit testing
        '''

        for channel in self.channels.values():
            await channel.scrape(
                already_ingested_videos=already_ingested_videos,
                filename=filename
            )

    async def import_videos(self, already_ingested_videos: dict[str, dict],
                            max_api_requests: int = 1000) -> None:
        '''
        Import the videos from the YouTube channel
        '''

        for channel in self.channels.values():
            await channel.import_videos(
                already_ingested_videos, max_api_requests=max_api_requests
            )

    async def get_videos(self, already_ingested_videos: dict[str, dict] = {},
                         max_api_requests: int = 1000, filename: str = None):
        '''
        Get videos from YouTube, either using scraping or the YouTube data API.

        The environment variable 'YOUTUBE_CHANNEL' is used to select the
        channel(s) to scrape from. Multiple channels can be specified by
        providing a comma-separated list of channel names.

        If the environment variable 'YOUTUBE_API_KEY' is set, the YouTube data
        API is called to import the videos. Otherwise, the YouTube website is
        scraped

        :param already_ingested_videos: a dictionary with the video ID as key
        and the data retrieved from the member data store as value
        :param max_api_requests: maximimum number of YouTube data API requests
        to send. Each 'search' API call consumes 100 tokens out of the default
        limit of YouTube for 10k tokens. The max_api_requests is per channel,
        so if there are multiple channels, you should specify a fraction of
        100 requests. This parameter is only used for import using the YouTube
        data API, not for when scraping the YouTube website.
        :param filename: scrape content from a file instead of the website,
        only supported for scraping, not for importing using the YouTube data
        API
        '''

        if not self.integration_enabled:
            raise ValueError('YouTube integration is not enabled')

        if not self.youtube_api_integration_enabled():
            await self.scrape_videos(
                already_ingested_videos, filename=filename
            )

            return

        if filename:
            raise ValueError('Importing from a file is not supported')

        await self.import_videos(already_ingested_videos, max_api_requests)
