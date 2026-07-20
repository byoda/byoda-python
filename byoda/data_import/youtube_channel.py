'''
Model a Youtube channel


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import logging
import os

from uuid import UUID
from uuid import uuid4

from shutil import rmtree
from random import random
from tempfile import mkdtemp
from logging import Logger
from logging import getLogger
from datetime import UTC
from datetime import datetime

import country_converter

from anyio import sleep

from yt_dlp import YoutubeDL

from byoda.datamodel.claim import Claim
from byoda.datamodel.table import Table
from byoda.datamodel.member import Member
from byoda.datamodel.table import QueryResult
from byoda.datamodel.sqltable import ArraySqlTable
from byoda.datamodel.datafilter import DataFilterSet

from byoda.datatypes import IngestStatus

from byoda.datastore.data_store import DataStore

from byoda.storage.filestorage import FileStorage
from byoda.storage.postgres import PostgresStorage

from byoda.exceptions import ByodaException, ByodaRuntimeError, ByodaValueError

from byoda import config

from .youtube_video import YouTubeVideo
from .youtube_thumbnail import YouTubeThumbnail
from .youtube_external_link import YouTubeExternalLink
from .youtube_streams import TARGET_VIDEO_STREAMS
from .youtube_streams import TARGET_AUDIO_STREAMS
from .scrape_exchange_youtube import ScrapeExchangeValidationError
from .scrape_exchange_youtube import ScrapeExchangeYouTubeClient
from .scrape_exchange_youtube import channel_from_payload
from .scrape_exchange_youtube import normalize_youtube_channel
from .scrape_exchange_youtube import video_from_payload

_LOGGER: Logger = getLogger(__name__)

YOUTUBE_URL: str = 'https://www.youtube.com'


class YouTubeChannel:
    DATASTORE_CLASS_NAME: str = 'channels'

    # Path to Deno binary for yt-dlp
    # Install Deno with from https://deno.land/#installation
    # ie. with 'curl -fsSL https://deno.land/install.sh | sh'
    DENO_PATH: str = os.environ.get('HOME') + '/.deno/bin/deno'

    # yt-dlp requires a PO token. Install with:
    # docker run --name bgutil-provider -d -p 4416:4416 --init brainicism/bgutil-ytdlp-pot-provider  # noqa: E501
    PO_TOKEN_URL: str = 'http://localhost:4416'

    def __init__(
        self, name: str = None, channel_id: str = None,
        title: str | None = None, ingest: bool = False,
        consent_cookies: dict[str, str] | None = None,
        user_agent: str | None = None,
        lock_file: str = None, storage_driver: FileStorage | None = None
    ) -> None:
        '''
        Models a YouTube channel

        :param name: the name of the channel as it appears in the vanity URL,
        i.e., for https://www.youtube.com/@HistoryMatters, name is
        'HistoryMatters'
        :param channel_id: The YouTube channel ID, i.e. the last part of:
        https://www.youtube.com/channel/UC22BdTgxefuvUivrjesETjg
        :param ingest: whether to ingest the A/V streams of the scraped assets
        :param consent_cookies: cookies to use to bypass consent pages
        :param user_agent: User-Agent string to use for HTTP requests
        :param lock_file: path to lock file to prevent concurrent runs
        :param storage_driver: storage driver to use for persisting media
        '''

        self.lock_file: str = lock_file
        self.storage_driver: FileStorage | None = storage_driver
        self.consent_cookies: dict[str, str] = consent_cookies or {}
        self.user_agent: str | None = user_agent
        self._work_dir: str = mkdtemp(dir='/tmp')

        self.download_client: YoutubeDL | None = None

        # This is the channel UUID from byotube.json
        self.channel_id: UUID | None = None

        self.name: str | None = name
        self.title: str | None = title

        self.youtube_url: str | None = None
        if self.name:
            self.name = normalize_youtube_channel(self.name)
            self.youtube_url = f'{YOUTUBE_URL}/@{self.name.replace(" ", "")}'

        # This is the youtube channel ID
        self.youtube_channel_id: str | None = channel_id

        self.description: str | None = None
        self.keywords: set[str] = set()
        self.categories: set[str] = set()
        self.verified: bool = False
        self.is_family_safe: bool = False
        self.available_country_codes: set[str] = set()
        self.channel_thumbnails: set[YouTubeThumbnail] = set()
        self.country: str | None = None
        self.joined_date: datetime | None = None

        # This thumbnail is used for the YouTubeVideo.channel_thumbnail
        self.channel_thumbnail: YouTubeThumbnail | None = None

        self.banners: set[YouTubeThumbnail] = set()
        self.external_urls: set[YouTubeExternalLink] = set()
        self.claims: list[Claim] = []

        # YouTube does not seem to keep these RSS feeds up to date
        self.rss_url: str | None = None

        # The number of subscribers and views are not always available
        self.subscriber_count: int | None = None
        self.video_count: int | None = None
        self.view_count: int | None = None
        self.courses: list[dict[str, any]] = []
        self.playlists: list[dict[str, any]] = []
        self.posts: list[dict[str, any]] = []
        self.merch: list[dict[str, any]] = []
        self.channel_links: list[dict[str, any]] = []
        self.video_ids: list[str] = []

        self.asset_ingest_enabled: bool = False
        self.ingest_videos: bool = ingest

        self.videos: dict[YouTubeVideo] = {}

    def __del__(self) -> None:
        rmtree(self._work_dir, ignore_errors=True)

    def as_dict(self) -> dict[str, any]:
        data: dict[str, any] = {
            'created_timestamp': datetime.now(tz=UTC),
            'channel_id': self.channel_id,
            'channel': self.name.lstrip('@'),
            'title': self.title,
            'description': self.description,
            'keywords': list(self.keywords),
            'categories': list(self.categories),
            'is_family_safe': self.is_family_safe,
            'available_country_codes': list(self.available_country_codes),
            'channel_thumbnails': [
                t.as_dict() for t in self.channel_thumbnails or set()
            ],
            'banners': [b.as_dict() for b in self.banners or set()],
            'external_urls': [
                el.as_dict() for el in self.external_urls or set()
            ],
            'publisher_channel_id': self.youtube_channel_id,
            'publisher_joined_date': self.joined_date,
            'publisher_rss_url': self.rss_url,
            'publisher_verified': self.verified,
            'publisher_platform_followers':
                self.subscriber_count or 0,
            'publisher_platform_videos': self.video_count or 0,
            'publisher_platform_views': self.view_count or 0,
            'courses': self.courses,
            'playlists': self.playlists,
            'posts': self.posts,
            'merch': self.merch,
            'channel_links': self.channel_links,
            'video_ids': self.video_ids,
            'claims': [],
        }

        if self.country:
            ccode: str = country_converter.convert(
                self.country, to='ISO2', not_found=None
            )
            data['country_code'] = ccode

        return data

    def update_lock_file(self) -> None:
        '''
        We update the lock file every time we do something so
        we can be more aggressive with removing stale lock files
        '''

        with open(self.lock_file, 'w') as lock_file:
            lock_file.write('1')

    def _setup_yt_dlp(self, with_download: bool = False,
                      video_formats: set[str] = TARGET_VIDEO_STREAMS,
                      audio_formats: set[str] = TARGET_AUDIO_STREAMS
                      ) -> YoutubeDL | None:
        '''
        Returns a yt-dlp YouTubeDL client
        '''

        if with_download and not self.ingest_videos:
            return

        if with_download and self.download_client:
            return self.download_client

        if not with_download:
            return None

        http_headers: dict[str, str] = {}
        if self.user_agent:
            http_headers['User-Agent'] = self.user_agent
        if self.consent_cookies:
            http_headers['Cookie'] = '; '.join(
                f'{k}={v}' for k, v in self.consent_cookies.items()
            )

        ydl_opts: dict[str, any] = {
            'quiet': not config.debug,
            'verbose': config.debug,
            'logger': _LOGGER,
            'noprogress': True,
            'no_color': True,
            'format': 'all',
            'http_headers': http_headers,
            'js_runtimes': {'deno': {'path': self.DENO_PATH}},
            'extractor_args': {
                'youtube': {
                    'player-client': 'default,mweb',
                    'youtubepot-bgutilhttp:base_url': self.PO_TOKEN_URL
                }
            }
        }

        if with_download:
            ydl_opts.update(
                {
                    'format': ','.join(video_formats | audio_formats),
                    'outtmpl':
                        {'default': 'asset-%(id)s.%(format_id)s.%(ext)s'},
                    'paths': {'home': self._work_dir, 'temp': self._work_dir},
                    'fixup': 'never',
                    'min_sleep_interval': 1,
                    'max_sleep_interval': 3,
                    'sleep_interval_requests': 1,
                }
            )

        client: YoutubeDL = YoutubeDL(ydl_opts)
        self.download_client = client

        return client

    async def persist_channel_info_media(
        self, member: Member, data_store: DataStore,
        custom_domain: str | None = None
    ) -> None:
        '''
        Persist the channel thumbnails and banners to storage

        :param member:
        :param data_store:
        :param storage_driver:
        :param custom_domain: what hostname should be used in content URLs if
        no CDN is used
        '''

        if not self.storage_driver:
            _LOGGER.warning(
                'No storage driver provided, cannot persist channel media',
            )
            raise ValueError('No storage driver provided')

        log_data: dict[str, str] = {'channel': self.name}

        _LOGGER.debug('Persisting channel', extra=log_data)

        table: ArraySqlTable = data_store.get_table(
            member.member_id, YouTubeChannel.DATASTORE_CLASS_NAME
        )
        data_filter: DataFilterSet = DataFilterSet(
            {'channel': {'eq': self.name}}
        )
        channel_data: dict[str, any] = self.as_dict()
        cursor: str = table.get_cursor_hash(channel_data, member.member_id)

        rows: list[QueryResult] | None = await table.query(
            data_filters=data_filter
        )
        if rows:
            await self._update_channel_stats(table, cursor, data_filter)
            return

        self.channel_id = self.channel_id or uuid4()
        channel_data: dict[str, any] = self.as_dict()
        cursor: str = table.get_cursor_hash(channel_data, member.member_id)

        log_data['channel_id'] = str(self.channel_id)
        _LOGGER.debug(
            'Channel is not yet in the data store', extra=log_data
        )

        video_id: UUID = uuid4()

        dirpath: str = mkdtemp(dir='/tmp')
        thumbnail: YouTubeThumbnail
        for thumbnail in self.channel_thumbnails:
            await thumbnail.ingest(
                video_id=video_id, storage_driver=self.storage_driver,
                member=member, work_dir=dirpath,
                custom_domain=custom_domain
            )

        banner: YouTubeThumbnail
        for banner in self.banners:
            await banner.ingest(
                video_id=video_id, storage_driver=self.storage_driver,
                member=member, work_dir=dirpath,
                custom_domain=custom_domain
            )

        rmtree(dirpath, ignore_errors=True)

        await table.append(
            channel_data, cursor, origin_id=None,
            origin_id_type=None, origin_class_name=None
        )
        _LOGGER.debug('Created channel in the data store', extra=log_data)

    async def _update_channel_stats(self, table: ArraySqlTable, cursor: str,
                                    data_filter: DataFilterSet) -> None:
        data: dict[str, any] = {
            'publisher_platform_followers': self.subscriber_count,
            'publisher_platform_views': self.view_count,
            'publisher_platform_videos': self.video_count,
        }
        await table.update(
            data, cursor, data_filter, None, None, None,
            placeholder_function=PostgresStorage.get_named_placeholder
        )

        log_data: dict[str, str] = {'channel': self.name} | data
        _LOGGER.info(
            'Updated channel followers, videos, and views', extra=log_data
        )

    async def scrape_videos(
        self, member: Member, data_store: DataStore,
        video_table: Table,
        bento4_directory: str | None = None,
        moderate_request_url: str | None = None,
        moderate_jwt_header: str | None = None,
        moderate_claim_url: str | None = None, ingest_interval: int = 0,
        custom_domain: str | None = None,
    ) -> int:
        '''
        Imports videos from Scrape.Exchange and optionally stores media files
        downloaded directly from YouTube.

        :param member: the member to use for the data store
        :param data_store: the data store to use for storing the video metadata
        :param storage_driver: the storage driver to use for repackaging
        :param beno4_directory: the directory where the Bento4 binaries are
        :param moderate_request_url: the URL to use for moderation requests
        :param moderate_jwt_header: the JWT header to use for moderation
        requests
        :param moderate_claim_url: the URL to use for moderation claims
        :param ingest_interval: the interval in seconds between ingests
        :param custom_domain: the custom domain to use for the video URLs
        :returns: number of imported videos
        :raises: ByodaRuntimeError, ByodaValueError, ByodaException
        '''

        log_extra: dict[str, str] = {'channel': self.name}

        if not self.name:
            raise ByodaValueError(
                'No channel name provided', loglevel=logging.ERROR,
                extra=log_extra
            )

        client = ScrapeExchangeYouTubeClient()
        videos_imported: int = 0
        try:
            channel_result = await client.get_channel_payload(self.name)
            if not channel_result:
                _LOGGER.info(
                    'No Scrape.Exchange channel metadata found',
                    extra=log_extra,
                )
                return 0

            channel_envelope, channel_payload = channel_result
            try:
                channel_from_payload(channel_payload, self)
            except ScrapeExchangeValidationError as exc:
                _LOGGER.info(
                    f'Skipping channel with invalid Scrape.Exchange payload: '
                    f'{exc}',
                    extra=log_extra | {
                        'envelope': channel_envelope,
                    },
                )
                return 0

            await self.persist_channel_info_media(
                member, data_store, custom_domain=custom_domain
            )

            if self.ingest_videos:
                self.download_client = self._setup_yt_dlp(with_download=True)

            channel_handle: str = normalize_youtube_channel(self.name)
            async for video_envelope, video_payload in client.iter_payloads(
                'video', platform_creator_id=channel_handle,
            ):
                try:
                    video: YouTubeVideo = video_from_payload(
                        video_payload,
                        channel_name=self.name,
                        channel_thumbnail=self.channel_thumbnail,
                        download_client=self.download_client,
                        storage_driver=self.storage_driver,
                    )
                except ScrapeExchangeValidationError as exc:
                    _LOGGER.info(
                        'Skipping invalid Scrape.Exchange video payload',
                        extra=log_extra | {
                            'error': str(exc),
                            'envelope': video_envelope,
                        },
                    )
                    continue

                log_extra['video_id'] = video.video_id
                log_extra['ingest_status'] = video.ingest_status.value

                if await self._should_skip_video(video, video_table):
                    continue

                if self.lock_file:
                    self.update_lock_file()

                _LOGGER.debug('Persisting video', extra=log_extra)
                try:
                    result: bool | None = await video.persist(
                        member,
                        ingest_asset=self.ingest_videos,
                        video_table=video_table,
                        bento4_directory=bento4_directory,
                        moderate_request_url=moderate_request_url,
                        moderate_jwt_header=moderate_jwt_header,
                        moderate_claim_url=moderate_claim_url,
                        custom_domain=custom_domain
                    )

                    if result is None:
                        log_extra['ingest_status'] = video.ingest_status.value
                        _LOGGER.debug(
                            'Failed to persist video', extra=log_extra
                        )
                    else:
                        videos_imported += 1
                except ByodaRuntimeError:
                    pass
                except ByodaException:
                    raise
                except Exception as exc:
                    raise ByodaValueError(
                        'Failed to persist video', extra=log_extra,
                        loglevel=logging.INFO
                    ) from exc

                if ingest_interval:
                    random_delay: float = \
                        random() * ingest_interval + ingest_interval / 2
                    _LOGGER.debug(
                        'Sleeping between ingesting assets for a channel',
                        extra=log_extra | {'seconds': random_delay}
                    )
                    await sleep(random_delay)

            _LOGGER.debug(
                f'Imported {videos_imported} videos from Scrape.Exchange',
                extra=log_extra
            )
            return videos_imported
        finally:
            await client.close()

    async def _should_skip_video(
        self, video: YouTubeVideo, table: Table
    ) -> bool:
        '''
        Decide whether a video already in the local data store should be
        skipped for this import pass.
        '''

        log_data: dict[str, str] = {
            'channel': self.name, 'video_id': video.video_id
        }
        data_filter: DataFilterSet = DataFilterSet(
            {'publisher_asset_id': {'eq': video.video_id}}
        )
        result: list[QueryResult] | None = await table.query(data_filter)
        if not result:
            return False

        status: IngestStatus | str | None = result[0][0].get('ingest_status')
        try:
            if isinstance(status, str):
                status = IngestStatus(status)
        except ValueError:
            status = IngestStatus.NONE

        if not self.ingest_videos and status == IngestStatus.EXTERNAL:
            _LOGGER.debug(
                'Skipping video as it is already ingested and AV ingest is '
                'not enabled',
                extra=log_data,
            )
            return True
        if status == IngestStatus.PUBLISHED:
            _LOGGER.debug(
                'Skipping video that is already published',
                extra=log_data,
            )
            return True
        return False
