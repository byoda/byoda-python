'''
Import data from Youtube


Takes as input environment variables
YOUTUBE_CHANNEL

Metadata comes from Scrape.Exchange's filter API. If video media is downloaded,
the media files are still downloaded directly from YouTube with yt-dlp.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import os

from uuid import UUID
from random import sample
from logging import Logger
from logging import getLogger

from byoda.datamodel.member import Member
from byoda.datamodel.table import Table
from byoda.datamodel.table import QueryResult
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.dataclass import SchemaDataItem

from byoda.datastore.data_store import DataStore

from byoda.exceptions import ByodaRuntimeError
from byoda.storage.filestorage import FileStorage

from .youtube_channel import YouTubeChannel

_LOGGER: Logger = getLogger(__name__)

class YouTube:
    ENVIRON_CHANNEL: str = 'YOUTUBE_CHANNEL'
    MODERATION_REQUEST_API: str = '/api/v1/moderate/asset'
    MODERATION_CLAIM_URL: str = '/claims/{state}/{asset_id}.json'
    INGEST_INTERVAL_SECONDS: int = 5

    def __init__(self, lock_file: str = None,
                 storage_driver: FileStorage | None = None,
                 storage_api_key: str | None = None
                 ) -> None:
        '''
        Constructor.
        '''

        self.integration_enabled: bool = YouTube.youtube_integration_enabled()

        self.lock_file: str = lock_file
        self.storage_driver: FileStorage | None = storage_driver

        self.storage_api_key: str | None = storage_api_key

        self.channels: dict[str, YouTubeChannel] = {}
        name: str
        for name in os.environ.get(YouTube.ENVIRON_CHANNEL, '').split(','):
            ingest: bool = False
            if ':' in name:
                name, ingest = name.split(':')
                ingest = bool(ingest)

            channel = YouTubeChannel(
                name, ingest=ingest, lock_file=self.lock_file,
                storage_driver=self.storage_driver
            )
            self.channels[name] = channel

    @staticmethod
    def youtube_integration_enabled() -> bool:
        result: bool = os.environ.get(YouTube.ENVIRON_CHANNEL) is not None

        _LOGGER.debug(f'YouTube integration enabled: {result}')

        return result

    @staticmethod
    async def load_ingested_channels(
        member_id: UUID, data_class: SchemaDataItem, data_store: DataStore
    ) -> set[str]:
        '''
        Load the ingested assets from the data store

        :param member_id: the member ID to use for the membership of the pod of
        the service
        :param data_store: The data store to use for storing the videos
        :returns: a dictionary with the video ID as key and the encoding
        status as value
        '''

        data: list[QueryResult] = await data_store.query(
            member_id, data_class, filters={}
        )

        known_channels: set[dict[str, str]] = set(
            [channel_data['channel'] for channel_data, _ in data or []]
        )

        _LOGGER.debug(f'Found {len(known_channels)} ingested channels')

        return known_channels

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
            video_data['publisher_asset_id']: {
                'published_timestamp': video_data['published_timestamp'],
                'ingest_status': video_data['ingest_status']
            }
            for video_data, _ in data or []
        }

        _LOGGER.debug(f'Found {len(known_videos)} ingested videos')

        return known_videos

    async def import_videos(
        self, member: Member, data_store: DataStore, video_table: Table,
        bento4_directory: str | None = None,
        moderate_request_url: str | None = None,
        moderate_jwt_header: str | None = None,
        moderate_claim_url: str | None = None,
        ingest_interval: int = INGEST_INTERVAL_SECONDS,
        custom_domain: str | None = None,
        max_videos: int = 200,
    ) -> None:
        '''
        Scrape channel(s) and videos from YouTube and persist them to storage.
        Videos are stored in the data store. If ingest of videos is enabled
        for a channel then the videos are downloaded, otherwise only the
        metadata is stored.

        :param member: our membership of the service
        :param data_store: where to store the channel info. Videos are stored
        using MemberData to trigger notifications on pub/sub
        :param video_table: the table of the data store to use for checking
        whether a video has already been ingested
        :param storage_driver: this parameter is required if we download the
        videos
        :param bento4_directory: this parameter is required if we download the
        assets and repackage them
        :param moderate_request_url: URL where to submit the request to review
        the moderation claim for thevideo
        :param moderate_jwt_header: JWT header to use for calling the
        moderation API
        :param moderate_claim_url:
        :param ingest_interval: interval in seconds between ingesting videos
        :param custom_domain: the custom domain to use for the storage URL if
        no CDN is used
        :param ValueError: if the storage driver is not specified and we ingest
        videos
        '''

        if not self.integration_enabled:
            raise ValueError('YouTube integration is not enabled')

        log_extra: dict[str, str] = {
            'member_id': str(member.member_id),
            'service_id': str(member.service_id),
            'channels': len(self.channels),
        }
        channels: list[YouTubeChannel] = list(self.channels.values())
        all_channels: list[YouTubeChannel] = sample(channels, k=len(channels))
        _LOGGER.debug('Found channels to import', extra=log_extra)

        if max_videos:
            log_extra['deprecated_max_videos'] = max_videos
        _LOGGER.info('Will import videos for all channels', extra=log_extra)

        for channel in all_channels:
            # Do not try to import channels without names, which could happen
            # if the YOUTUBE_CHANNEL has two ','s in a row or a
            # trailing ','
            if not channel:
                _LOGGER.debug('Got empty channel', extra=log_extra)
                continue

            log_extra['channel'] = channel.name
            _LOGGER.debug('Importing channel', extra=log_extra)

            if channel.ingest_videos and not self.storage_driver:
                raise ValueError(
                    'We need a storage driver to download videos',
                    extra=log_extra
                )
            try:
                await channel.scrape_videos(
                    member, data_store, video_table,
                    bento4_directory,
                    moderate_request_url=moderate_request_url,
                    moderate_jwt_header=moderate_jwt_header,
                    moderate_claim_url=moderate_claim_url,
                    ingest_interval=ingest_interval,
                    custom_domain=custom_domain,
                )
            except ByodaRuntimeError:
                pass

            # Release memory used by the import run
            channel.videos = []
