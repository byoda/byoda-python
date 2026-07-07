'''
Model a Youtube channel


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import logging
import os
import re

from uuid import UUID
from uuid import uuid4

from typing import Self
from shutil import rmtree
from random import random
from tempfile import mkdtemp
from logging import Logger
from logging import getLogger
from datetime import UTC
from datetime import datetime

import orjson
import country_converter

from anyio import sleep

from innertube import InnerTube

from yt_dlp import YoutubeDL

from byoda.datamodel.claim import Claim
from byoda.datamodel.table import Table
from byoda.datamodel.member import Member
from byoda.datamodel.table import QueryResult
from byoda.datamodel.sqltable import ArraySqlTable
from byoda.datamodel.datafilter import DataFilterSet

from byoda.datatypes import SocialNetworks
from byoda.datatypes import IngestStatus

from byoda.datastore.data_store import DataStore

from byoda.storage.filestorage import FileStorage
from byoda.storage.postgres import PostgresStorage

from byoda.util.test_tooling import convert_number_string
from byoda.util.string_parser import split_quoted_string

from byoda.exceptions import ByodaException, ByodaRuntimeError, ByodaValueError

from byoda import config

from .youtube_client import AsyncYouTubeClient
from .youtube_video import YouTubeVideo
from .youtube_thumbnail import YouTubeThumbnail
from .youtube_external_link import YouTubeExternalLink
from .youtube_streams import TARGET_VIDEO_STREAMS
from .youtube_streams import TARGET_AUDIO_STREAMS

_LOGGER: Logger = getLogger(__name__)

# Limits the amount of videos imported for a channel
# per run
MAX_CHANNEL_VIDEOS_PER_RUN: int = 40

HTTP_PREFIX: str = 'http://'
HTTPS_PREFIX: str = 'https://'


class YouTubeChannel:
    DATASTORE_CLASS_NAME: str = 'channels'

    CHANNEL_URL: str = AsyncYouTubeClient.SCRAPE_URL + '/{channel_name}'
    CHANNEL_URL_WITH_AT: str = \
        AsyncYouTubeClient.SCRAPE_URL + '/@{channel_name}'

    CHANNEL_ID_REGEX: re.Pattern[str] = re.compile(r'"externalId":"(.*?)"')
    CHANNEL_SCRAPE_REGEX_SHORT: re.Pattern[str] = re.compile(
        r'var ytInitialData = (.*?);'
    )
    CHANNEL_SCRAPE_REGEX: re.Pattern[str] = re.compile(
        r'var ytInitialData = (.*?);$'
    )
    RX_SCRAPE_CHANNEL_ID: re.Pattern[str] = re.compile(
        r'"externalId":"(.*?)"'
    )

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
        consent_cookies: dict[str, str] | None = AsyncYouTubeClient.CONSENT_COOKIES,        # noqa: E501
        user_agent: str | None = AsyncYouTubeClient.USER_AGENT,
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
        self.consent_cookies: dict[str, str] = consent_cookies
        self.user_agent: str | None = user_agent
        self._work_dir: str = mkdtemp(dir='/tmp')

        self.browse_client: YoutubeDL | None = None
        self.download_client: YoutubeDL | None = None

        # This is the channel UUID from byotube.json
        self.channel_id: UUID | None = None

        self.name: str | None = name
        self.title: str | None = title

        self.youtube_url: str | None = None
        if self.name:
            self.name = self.name.lstrip('@')
            self.youtube_url = YouTubeChannel.CHANNEL_URL_WITH_AT.format(
                channel_name=self.name.replace(' ', '')
            )

        self.web_client: AsyncYouTubeClient = AsyncYouTubeClient(
            consent_cookies=consent_cookies, user_agent=user_agent
        )

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
            'publisher_followers':
                self.subscriber_count or 0,
            'publisher_videos': self.video_count or 0,
            'publisher_views': self.view_count or 0,
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

        if not with_download and self.browse_client:
            return self.browse_client

        if with_download and self.download_client:
            return self.download_client

        ydl_opts: dict[str, any] = {
            'quiet': not config.debug,
            'verbose': config.debug,
            'logger': _LOGGER,
            'noprogress': True,
            'no_color': True,
            'format': 'all',
            'http_headers': dict(self.web_client.headers) | {
                'Cookie': '; '.join(
                    f'{k}={v}' for k, v in self.consent_cookies.items()
                )
            },
            'js_runtimes': {'deno': {'path': self.DENO_PATH}},
            'extractor_args': {
                'youtube': {
                    'player-client': 'default,mweb',
                    'youtubepot-bgutilhttp:base_url': self.PO_TOKEN_URL
                }
            }
        }

        # YouTubeDL browsing, instead of downloading, a video fails with
        # the below settings. So we only set them if downloading.
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
        if with_download:
            self.download_client = client
        else:
            self.browse_client = client

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
            'thirdparty_platform_followers': self.subscriber_count,
            'thirdparty_platform_views': self.view_count,
            'thirdparty_platform_videos': self.video_count,
        }
        await table.update(
            data, cursor, data_filter, None, None, None,
            placeholder_function=PostgresStorage.get_named_placeholder
        )

        log_data: dict[str, str] = {'channel': self.name} | data
        _LOGGER.info(
            'Updated channel followers, videos, and views', extra=log_data
        )

    def _extract_initial_data(self, html_content: str) -> dict | None:
        '''
        Extract ytInitialData from the HTML page

        :param html_content: Raw HTML content from YouTube page
        :returns: Parsed ytInitialData dictionary or None if not found
        :raises: ValueError: If a consent page is detected (only when consent
        cookies are not set)
        '''

        # Verified badge is hard to find otherwise
        self.verified = YouTubeChannel.extract_verified_status(
            page_data=html_content
        )

        # YouTube embeds data in a script tag as ytInitialData
        # Try multiple patterns as YouTube's format can vary
        patterns: list[str] = [
            r'ytInitialData\s*=\s*({.*?});',
            r'window\["ytInitialData"\] = ({.*?});',
        ]

        for pattern in patterns:
            match: re.Match[str] | None = re.search(
                pattern, html_content, re.DOTALL
            )
            if match:
                try:
                    return orjson.loads(match.group(1))
                except orjson.JSONDecodeError:
                    continue

        # If we couldn't find data, check if it's because of a consent page
        if ('consent.youtube.com' in html_content
                or 'consent.google.com' in html_content):
            raise ValueError(
                'Encountered YouTube consent page. The consent cookies may '
                'have expired or been rejected. Try setting '
                'use_consent_cookies=True when initializing the scraper.'
            )

        return None

    def _extract_handle(self, url: str, metadata: dict) -> str | None:
        '''Extract channel handle from URL or metadata'''
        # Try to extract from URL
        if '@' in url:
            parts: list[str] = url.split('@')
            if len(parts) > 1:
                handle: str = '@' + parts[1].split('/')[0].split('?')[0]
                return handle

        # Try from metadata
        if metadata.get('channelUrl'):
            channel_url: str = metadata['channelUrl']
            if '@' in channel_url:
                parts = channel_url.split('@')
                if len(parts) > 1:
                    return '@' + parts[1].split('/')[0]

        return None

    def _parse_thumbnails(self, thumbnails_list: list[dict]
                          ) -> dict[str, dict]:
        '''
        Parse thumbnail data into schema format
        '''

        thumbnails: dict = {}

        if len(thumbnails_list) >= 1:
            thumbnails['default'] = self._parse_thumbnail(thumbnails_list[0])
        if len(thumbnails_list) >= 2:
            thumbnails['medium'] = self._parse_thumbnail(thumbnails_list[1])
        if len(thumbnails_list) >= 3:
            thumbnails['high'] = self._parse_thumbnail(thumbnails_list[-1])

        return thumbnails

    def _parse_thumbnail(self, thumbnail: dict) -> dict[str, any]:
        '''
        Parse a single thumbnail
        '''

        return {
            'url': thumbnail.get('url'),
            'width': thumbnail.get('width'),
            'height': thumbnail.get('height'),
        }

    @staticmethod
    def _extract_links(initial_data: dict) -> set[dict[str, str]]:
        '''
        Extract external links from the header dict of the channel 'about'
        data.
        '''

        links: set = set()

        # Links are typically in the header or about section
        header: dict[str, any] = initial_data.get('header', {})
        header_renderer: dict[str, any] = (
            header.get('c4TabbedHeaderRenderer') or
            header.get('pageHeaderRenderer') or
            {}
        )

        # Check for primary links
        if not header_renderer:
            return set()

        primary_links: list[dict[str, any]] = header_renderer.get(
            'headerLinks', {}
        ).get(
            'channelHeaderLinksRenderer', {}
        ).get(
            'primaryLinks', []
        )
        for link in primary_links:
            url: str = link.get(
                'navigationEndpoint', {}
            ).get(
                'urlEndpoint', {}
            ).get('url')

            if url:
                links.add(
                    {
                        'title': link.get(
                            'title', {}
                        ).get(
                            'simpleText', 'Link'
                        ),
                        'url': url
                    }
                )

        return links

    @staticmethod
    def parse_external_urls(data: dict[str, any]) -> set[YouTubeExternalLink]:
        '''
        Parses the external URLs out of the YouTube channel about page
        'about renderer'

        :param data: the YouTube channel page as a dict
        :returns: list of external URLs
        '''

        external_links: set[YouTubeExternalLink] = set()

        field_name: str = 'channelExternalLinkViewModel'
        priority: int = 10
        for item in data or []:
            item_data: dict[str, dict[str, any]] = item.get(field_name)
            if not item_data:
                continue

            title: str = item_data.get('title', {}).get('content', {})
            url: str = item_data.get('link', {}).get('content')
            external_link: YouTubeExternalLink | None = \
                YouTubeChannel._generate_external_link(url, priority, title)
            priority += 10
            if external_link:
                external_links.add(external_link)

        return external_links

    async def scrape(self) -> dict[str, any]:
        '''
        Scrape the About tab for information. This does not include data
        about the videos for the channel as multiple requests are needed
        to get that data. Use get_videos_page() and parse_channel_video_data()
        to get the videos from the channel.
        '''

        about_url: str = self.youtube_url.rstrip('/') + '/about'

        log_extra: dict[str, str] = {'channel': self.name, 'url': about_url}

        page_data: str | None = await self.web_client.get(about_url)

        self.youtube_channel_id = YouTubeChannel.extract_channel_id(page_data)

        initial_data: dict | None = self._extract_initial_data(page_data)

        if not initial_data:
            _LOGGER.warning(
                'Could not extract data from page', extra=log_extra
            )
            return {}

        # This parses the channel metadata
        metadata: dict[str, any] = initial_data.get(
            'metadata', {}
        ).get('channelMetadataRenderer', {})
        if metadata:
            self._parse_channel_about_metadata(metadata)

        about_renderer: dict | None = self._find_about_renderer(
            initial_data
        )
        if not about_renderer:
            _LOGGER.warning('Could not find about tab renderer')
            return {}

        self._parse_thumbnails_banners(metadata, initial_data)

        self._parse_channel_about_data(about_renderer)

    def _find_about_renderer(self, initial_data: dict) -> dict | None:
        '''
        Gets the channel data from the aboutChannelViewModel
        '''

        endpoints: list[dict[str, str]] = initial_data.get(
            'onResponseReceivedEndpoints', []
        )
        endpoint: dict[str, str]
        for endpoint in endpoints:
            section_list: list = YouTubeChannel.parse_nested_dicts(
                [
                    'showEngagementPanelEndpoint', 'engagementPanel',
                    'engagementPanelSectionListRenderer',
                    'content', 'sectionListRenderer', 'contents'
                ], endpoint, list
            )

            item: dict
            for item in section_list or []:
                item_section: dict[str, any] = item.get(
                    'itemSectionRenderer', {}
                ).get('contents', {})
                for content_item in item_section or []:
                    about_view_model: dict[str, dict[str, str]] | None = \
                        YouTubeChannel.parse_nested_dicts(
                            [
                                'aboutChannelRenderer', 'metadata',
                                'aboutChannelViewModel'
                            ], content_item, dict
                        )
                    if about_view_model:
                        return about_view_model

        _LOGGER.warning(
            'Could not find about tab renderer',
            extra={'channel': self.name, 'url': self.youtube_url}
        )
        return None

    def _extract_simple_text(self, text_obj: dict | str | None) -> str | None:
        '''
        Extracts simple text from a YouTube object

        :return: extracted text or None
        '''

        if isinstance(text_obj, str):
            return text_obj

        if text_obj.get('content'):
            return text_obj['content']

        if text_obj.get('simpleText'):
            return text_obj['simpleText']

        if text_obj.get('runs'):
            return ''.join(run.get('text', '') for run in text_obj['runs'])

        return None

    def _parse_channel_about_metadata(self, metadata: dict) -> None:
        '''Parse channel data from ytInitialData channelMetadataRenderer'''

        self.youtube_channel_id = metadata.get(
            'externalId', self.youtube_channel_id
        )
        self.name = self.name or metadata.get('title')
        self.title = self.title or metadata.get('title')

        self.description = metadata.get('description', self.description)
        self.rss_url = metadata.get('rssUrl', self.rss_url)

        self.available_country_codes = self.available_country_codes | \
            set(metadata.get('availableCountryCodes', []))

        vanity_url: str = metadata.get('vanityChannelUrl')
        self.external_urls.add(
            YouTubeExternalLink(
                name='YouTube', url=vanity_url, priority=0,
            )
        )

        self.keywords = self.keywords | split_quoted_string(
            metadata.get('keywords')
        )

        self.is_family_safe = metadata.get(
            'madeForKids', False
        )

    def _parse_channel_about_data(self, about_renderer: dict) -> None:
        '''
        Parse channelAboutFullMetadataRenderer data
        '''

        joined_text: str = self._extract_simple_text(
            about_renderer.get('joinedDateText')
        )
        if joined_text:
            joined_text = joined_text.lstrip('Joined ')
            # YouTubeClient sets locale to en-US, so we parse accordingly
            self.joined_date = self.joined_date or datetime.strptime(
                joined_text, '%b %d, %Y'
            )

        self.view_count = self.view_count or convert_number_string(
            self._extract_simple_text(about_renderer.get('viewCountText'))
        )

        self.video_count = self.video_count or convert_number_string(
            self._extract_simple_text(about_renderer.get('videoCountText'))
        )

        self.subscriber_count = self.subscriber_count or convert_number_string(
            self._extract_simple_text(
                about_renderer.get('subscriberCountText')
            )
        )

        self.external_urls = self.external_urls | \
            YouTubeChannel.parse_external_urls(
                about_renderer.get('links', [])
            )

        # Redundant with metadata parsing, still kept as fallback if
        # YouTube changes metadata structure
        self.description = self.description or self._extract_simple_text(
            about_renderer.get('description', {})
        )

        # Redundant with metadata parsing, still kept as fallback if
        # YouTube changes metadata structure
        self.country = self.country or self._extract_simple_text(
            about_renderer.get('country')
        )

    def parse_channel_video_data(self, page_html: str) -> None:
        '''
        Parses the info from the channel 'videos' page

        :param page_data: the text of the 'videos' page for the channel
        :returns: (none)
        '''

        log_data: dict[str, str] = {'channel': self.name}

        if not page_html:
            _LOGGER.warning(
                'No page data to parse from channel info', extra=log_data
            )
            return None

        self.youtube_channel_id = self.youtube_channel_id or \
            YouTubeChannel.extract_channel_id(page_html)

        page_data: dict[str, any] = self._extract_initial_data(page_html)
        if not page_data:
            _LOGGER.warning(
                'No parsed data found for channel', extra=log_data
            )
            return None

        self.channel_thumbnails = self.channel_thumbnails | \
            YouTubeChannel.parse_thumbnails(page_data)

        self._set_channel_video_thumbnail()

        self.banners: set[YouTubeThumbnail] = self.banners | \
            YouTubeChannel.parse_banners(page_data)

        self.subscriber_count = \
            YouTubeChannel.parse_subscriber_count(page_data)

        self.video_count: int | None = \
            YouTubeChannel.parse_video_count(page_data)

        # We can't get total views for the channel from the videos page,
        # we can get it from the about page though so no worries here

        channel_info: dict[str, any] | None = page_data.get(
            'metadata', {}
        ).get(
            'channelMetadataRenderer'
        )
        if not channel_info:
            _LOGGER.info(
                'No channel metadata found for channel', extra=log_data
            )
            raise ValueError('No channel metadata found')

        # We already get the channel name from the channel metadata but we
        # keep it here in case YouTube changes their metadata structure
        self.name: str = self.name or channel_info.get('title', '').lstrip('@')
        self.title = self.title or channel_info.get('title')

        # We already get description from about metadata but we
        # keep it here in case YouTube changes their metadata structure
        self.description = channel_info.get('description', self.description)

        # We already get keywords from about metadata but we
        # keep it here in case YouTube changes their metadata structure
        keywords_data: str = channel_info.get('keywords')
        self.keywords = self.keywords | split_quoted_string(keywords_data)

        # We get the this data already from the about metadata but we
        # keep it here in case YouTube changes their metadata structure
        self.is_family_safe = channel_info.get(
            'isFamilySafe', self.is_family_safe
        )

    def _set_channel_video_thumbnail(self) -> None:
        # The channel thumbnail used for videos is the smallestavailable
        if self.channel_thumbnails:
            self.channel_thumbnail = sorted(self.channel_thumbnails)[0]

    def _parse_thumbnails_banners(self, metadata: dict[str, any],
                                  initial_data: dict[str, any]) -> None:

        metadata_rows: dict | None = YouTubeChannel.parse_nested_dicts(
            [
                'header', 'pageHeaderRenderer', 'content',
                'pageHeaderViewModel'
            ], initial_data, dict
        )

        self.external_urls = self.external_urls | \
            YouTubeChannel._extract_links(initial_data)

        # Thumbnails
        header: dict[str, dict[str, any]] = initial_data.get('header', {})
        # Try different header types
        header_renderer: dict[str, any] = (
            header.get('c4TabbedHeaderRenderer') or
            header.get('pageHeaderRenderer') or
            {}
        )

        if 'avatar' in metadata and 'thumbnails' in metadata['avatar']:
            self.channel_thumbnails = self.channel_thumbnails | \
                YouTubeChannel.parse_thumbnails(
                    metadata['avatar']['thumbnails']
                )
        elif ('avatar' in header_renderer and
                'thumbnails' in header_renderer['avatar']):
            self.channel_thumbnails = self.channel_thumbnails | \
                YouTubeChannel.parse_thumbnails(
                    header_renderer['avatar']['thumbnails']
                )

        self._set_channel_video_thumbnail()

        # Banner
        banners: list[dict[str, str]] = metadata_rows.get(
            'banner', {}
        ).get(
            'imageBannerViewModel', {}
        ).get(
            'image', {}
        ).get(
            'sources', []
        )
        if not banners:
            banners = header_renderer.get('banner', {}).get('thumbnails', [])

        for banner in banners:
            self.banners.add(
                YouTubeThumbnail(size=None, data=banner)
            )

            tabs: list = YouTubeChannel.parse_nested_dicts(
                ['contents', 'twoColumnBrowseResultsRenderer', 'tabs'],
                initial_data, list
            )
            if not tabs or len(tabs) < 2 or 'tabRenderer' not in tabs[1]:
                _LOGGER.warning('Scraped video does not have 2 tabs')

    async def get_videos_page(self) -> str:
        '''
        Gets the videos page HTML content

        :returns: HTML content of the videos page
        '''

        videos_url: str = self.youtube_url.rstrip('/') + '/videos'

        log_extra: dict[str, str] = {'channel': self.name, 'url': videos_url}

        page_html: str | None = await self.web_client.get(videos_url)

        if not page_html:
            _LOGGER.warning(
                'No page data found for channel videos page',
                extra=log_extra
            )
            return ''

        return page_html

    async def scrape_videos(
        self, member: Member, data_store: DataStore,
        video_table: Table,
        bento4_directory: str | None = None,
        moderate_request_url: str | None = None,
        moderate_jwt_header: str | None = None,
        moderate_claim_url: str | None = None, ingest_interval: int = 0,
        custom_domain: str | None = None,
        max_videos_per_channel: int = 0,
    ) -> int:
        '''
        Scrapes videos from the YouTube website and optionally stores them in
        the data store

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
        :param max_videos_per_channel: the maximum number of videos to ingest
        :param already_ingested_videos: dictionary of ingested assets with
        YouTube video IDs as keys and as values a dict with ingest_status
        and published_timestamp
        :returns: number of pages scraped
        :raises: ByodaRuntimeError, ByodaValueError, ByodaException
        '''

        log_extra: dict[str, str] = {'channel': self.name}

        if not self.name:
            raise ByodaValueError(
                'No channel name provided', loglevel=logging.ERROR,
                extra=log_extra
            )

        page_html: str = await self.get_videos_page()

        if not page_html:
            raise ByodaRuntimeError(
                'No page data found for channel', loglevel=logging.INFO,
            )

        self.parse_channel_video_data(page_html)

        await self.persist_channel_info_media(
            member, data_store, custom_domain=custom_domain
        )

        self.video_ids: list[str] = []
        try:
            self.video_ids = await self.get_video_ids()
            if not self.video_ids:
                raise ByodaValueError(
                    'No video IDs extracted', loglevel=logging.INFO,
                    extra=log_extra
                )
        except Exception as exc:
            raise ByodaException(
                f'Failed to extract video IDs: {exc}', extra=log_extra,
                loglevel=logging.INFO
            ) from exc

        self.browse_client = self._setup_yt_dlp(with_download=False)
        self.download_client = self._setup_yt_dlp(with_download=True)

        videos_imported: int = 0
        for video_id in self.video_ids:
            try:
                video: YouTubeVideo | None = await self.scrape_video(
                    video_id, video_table, self.ingest_videos,
                    self.channel_thumbnail
                )
                if not video:
                    continue
            except ByodaRuntimeError:
                continue
            except Exception as exc:
                raise ByodaException(
                    f'Failed to scrape video: {exc}', extra=log_extra,
                    loglevel=logging.INFO
                ) from exc

            log_extra['video_id'] = video.video_id
            log_extra['ingest_status'] = video.ingest_status.value

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

                videos_imported += 1
                if (max_videos_per_channel
                        and videos_imported >= max_videos_per_channel):
                    break
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

            video = None

        _LOGGER.debug(
            f'Scraped {len(self.videos)} videos from YouTube channel',
            extra=log_extra
        )

        return videos_imported

    @staticmethod
    def extract_channel_id(page_data: str) -> str:
        '''
        Extracts the YouTube channel ID (ie. 'gxefuvUivrjesETjg') from the
        channel page data

        :param page_data: channel description
        :returns: the YouTube channel ID
        '''
        if not page_data:
            _LOGGER.warning('No page data to extract channel ID from')

        match: re.Match[str] | None = \
            YouTubeChannel.CHANNEL_ID_REGEX.search(page_data)

        if match is None:
            raise ValueError('Channel ID not found')

        channel_id: str = match.group(1)

        return channel_id

    @staticmethod
    def extract_verified_status(page_data: str) -> bool:
        '''
        Extracts whether the channel is verified from the channel page data

        :param page_data: channel description
        :returns: whether the channel is verified
        '''
        if not page_data:
            _LOGGER.warning('No page data to extract verified status from')

        match: re.Match[str] | None = re.search(
            r'"tooltip"\s*:\s*"Verified"', page_data
        )
        return match is not None

    @staticmethod
    def find_nested_dicts(target: str, data: any, path: str = '<root>') -> any:
        '''
        Helper function to locate a wanted key in the nested dictionaries
        in the scraped data

        :param target: the key to search for
        :param data: the data to search in
        :param path: the path through the dict in the current data
        :returns: the value of the key
        '''

        if isinstance(data, dict):
            _LOGGER.debug(
                f'Target:{target} Path:{path} Keys:{','.join(data.keys())}'
            )
            if target in data:
                return data[target]

            for key, value in data.items():
                result: any = YouTubeChannel.find_nested_dicts(
                    target, value, f'{path}:{key}'
                )
                if result:
                    return result

        if isinstance(data, list):
            _LOGGER.debug(f'In list with {len(data)} items')
            for item in data:
                result: any = YouTubeChannel.find_nested_dicts(
                    target, item, f'{path}[]'
                )
                if result:
                    return result

        return None

    @staticmethod
    def parse_video_count(data: dict) -> int | None:
        '''
        Parse the video count from the scraped data

        :param data: the scraped data
        :returns: the subscriber count
        '''

        metadata_rows: str | any = YouTubeChannel.parse_nested_dicts(
            [
                'header', 'pageHeaderRenderer', 'content',
                'pageHeaderViewModel', 'metadata',
                'contentMetadataViewModel', 'metadataRows',
            ], data, list
        )

        for metadata_row in metadata_rows or []:
            metadata_parts: list[dict] = metadata_row.get(
                'metadataParts', []
            ) or []
            for metadata_part in metadata_parts:
                if isinstance(metadata_part.get('text'), dict):
                    content: str = metadata_part['text'].get('content', '')
                    if content and 'videos' in content:
                        youtube_video_count: int | None = \
                            convert_number_string(content)
                        return youtube_video_count

        _LOGGER.debug('Failed to parse videos count')
        return None

    @staticmethod
    def parse_subscriber_count(data: dict) -> int | None:
        '''
        Parse the subscriber count from the scraped data

        :param data: the scraped data
        :returns: the subscriber count
        '''

        metadata_rows: str | any = YouTubeChannel.parse_nested_dicts(
            [
                'header', 'pageHeaderRenderer', 'content',
                'pageHeaderViewModel', 'metadata',
                'contentMetadataViewModel', 'metadataRows',
            ], data, list
        )

        for metadata_row in metadata_rows or []:
            metadata_parts: list[dict] = metadata_row.get(
                'metadataParts', []
            ) or []
            for metadata_part in metadata_parts:
                if isinstance(metadata_part.get('text'), dict):
                    content: str = metadata_part['text'].get('content', '')
                    if content and 'subscribers' in content:
                        youtube_subs_count: int | None = \
                            convert_number_string(content)
                        return youtube_subs_count

        _LOGGER.debug('Failed to parse subscriber count')
        return None

    @staticmethod
    def parse_view_count(data: dict) -> int | None:
        '''
        Parse the total views count for the channel from the scraped data

        :param data: the scraped data
        :returns: the subscriber count
        '''

        try:
            views_data: dict | any = YouTubeChannel.parse_nested_dicts(
                [
                    'header', 'c4TabbedHeaderRenderer', 'viewCountText',
                    'simpleText'
                ], data, list
            )
            if not views_data:
                return None

            view_count: int | None = convert_number_string(views_data)

            return view_count
        except Exception as exc:
            _LOGGER.debug(f'Failed to parse views count: {exc}')
            return None

    @staticmethod
    def parse_thumbnails(data: dict[str, any]) -> set[YouTubeThumbnail]:
        '''
        Parses the thumbnails out of the YouTube channel page either
        scraped or retrieved using the InnerTube API
        '''

        thumbnails_data: list | None = YouTubeChannel.parse_nested_dicts(
            [
                'header', 'pageHeaderRenderer', 'content',
                'pageHeaderViewModel', 'image', 'decoratedAvatarViewModel',
                'avatar', 'avatarViewModel', 'image', 'sources'
            ], data, list
        )
        if not thumbnails_data:
            # If we can't parse the data from the channel scrape,
            # we try to get the data from the InnerTube API
            _LOGGER.debug(
                'Falling back to Innertube for channel thumbnails',
            )
            if isinstance(data, list):
                thumbnails_data = data
            else:
                thumbnails_data = \
                    data.get('thumbnail', {}).get('thumbnails', [])
                _LOGGER.debug('Data is a low-depth list')

        channel_thumbnails: set[YouTubeThumbnail] = set()
        for thumbnail_data in thumbnails_data:
            url: str | None = thumbnail_data.get('url')
            if (url and (
                    not url.startswith(HTTPS_PREFIX) or url.startswith('//'))):
                thumbnail_data['url'] = f'https:{url}'
            thumbnail = YouTubeThumbnail(None, thumbnail_data)
            channel_thumbnails.add(thumbnail)

        return channel_thumbnails

    @staticmethod
    def _generate_external_link(url: str, priority: int,
                                title: str | None = None
                                ) -> YouTubeExternalLink | None:
        # Strip of the protocol from the url
        if url.startswith(HTTP_PREFIX):
            url = url[len(HTTP_PREFIX):]
        elif url.startswith(HTTPS_PREFIX):
            url = url[len(HTTPS_PREFIX):]

        if not title:
            # Figure out with social network the url is pointing to
            name: str = url.split('/')[0]
            domain_parts: list[str] = name.split('.')
            # Strip of 'www'
            if domain_parts and domain_parts[0] == 'www':
                domain_parts = domain_parts[1:]

            if len(domain_parts) == 2:
                name = domain_parts[0]
            elif domain_parts[-1] in ('tt', 'uk', 'au', 'nz', 'ng'):
                name = domain_parts[-3]
            else:
                if url.startswith('and '):
                    # This is text ' and <n> more link<s>'
                    _LOGGER.debug(
                        f'TODO: call YT API to get the additional links: {url}'
                    )
                    return None
                else:
                    _LOGGER.debug(
                        f'Could not parse link name our of URL: {url}'
                    )
                    name = url

            title = SocialNetworks.get(name.lower(), 'www')
            _LOGGER.debug(f'Parsed external link label {name} ouf of {url}')

        return YouTubeExternalLink(
            name=title, url=f'https://{url}', priority=priority,
        )

    @staticmethod
    def parse_banners(data: dict[str, any]) -> set[YouTubeThumbnail]:
        '''
        Parses the banner images out of the YouTube channel page

        :param data: the YouTube channel page as a dict
        :returns: list of banners as YouTubeThumbnails
        '''

        banners: set[YouTubeThumbnail] = set()

        banner_type: str
        for banner_type in ['banner', 'tvBanner', 'mobileBanner']:
            banner_data: dict[str, str | int] | None = \
                YouTubeChannel.parse_nested_dicts(
                    [
                        'header', 'pageHeaderRenderer', 'content',
                        'pageHeaderViewModel', banner_type,
                        'imageBannerViewModel', 'image', 'sources',
                    ], data, list
                )

            thumbnail_data: dict[str, str | int]
            for thumbnail_data in banner_data or []:
                channel_banner: YouTubeThumbnail = YouTubeThumbnail(
                    None, thumbnail_data, display_hint=banner_type
                )
                _LOGGER.debug(f'Found banner: {channel_banner.url}')
                banners.add(channel_banner)

        return banners

    @staticmethod
    def parse_nested_dicts(keys: list[str], data: dict[str, any],
                           final_type: callable
                           ) -> object | list[object] | None:
        for key in keys:
            if key in data:
                data = data[key]
            else:
                return None

        if not isinstance(data, final_type):
            _LOGGER.debug(
                f'Expected value of {final_type} but got {type(data)}: {data}'
            )
            return None

        return data

    async def get_video_ids(self) -> list[str]:
        # Client for YouTube (Web)
        client = InnerTube('WEB', '2.20230728.00.00')

        video_ids: list[str] = []

        first_run: bool = True
        continuation_token: str = ''
        while first_run or continuation_token:
            # If this is the first video listing, browse the 'Videos' page
            if not continuation_token:
                first_run = False
                # Fetch the browse data for the channel
                channel_data: dict = client.browse(self.youtube_channel_id)

                # Extract the tab renderer for the 'Videos' tab of the channel
                tabs: list = YouTubeChannel.parse_nested_dicts(
                    ['contents', 'twoColumnBrowseResultsRenderer', 'tabs'],
                    channel_data, list
                )
                if not tabs or len(tabs) < 2 or 'tabRenderer' not in tabs[1]:
                    _LOGGER.warning('Scraped video does not have 2 tabs')
                    return []

                videos_tab_renderer: dict = tabs[1]['tabRenderer']

                # Make sure this tab is the 'Videos' tab
                if videos_tab_renderer['title'] != 'Videos':
                    _LOGGER.warning(
                        'Scraped channel does not have a "Videos" tab'
                    )
                    return []

                # Extract the browse params for the 'Videos' tab of the channel
                videos_params: str = \
                    videos_tab_renderer['endpoint']['browseEndpoint']['params']

                # Wait a bit so that Google doesn't suspect us of being a bot
                await AsyncYouTubeClient._delay()

                # Fetch the browse data for the channel's videos
                videos_data: dict = client.browse(
                    self.youtube_channel_id, params=videos_params
                )

                # Extract the contents list
                tabs = YouTubeChannel.parse_nested_dicts(
                    ['contents', 'twoColumnBrowseResultsRenderer', 'tabs'],
                    videos_data, list
                )
                contents: list = YouTubeChannel.parse_nested_dicts(
                    ['tabRenderer', 'content', 'richGridRenderer', 'contents'],
                    tabs[1], list
                )
            else:
                # Fetch more videos by using the continuation token
                continued_videos_data: dict = client.browse(
                    continuation=continuation_token
                )
                # Wait a bit so that Google doesn't suspect us of being a bot
                await AsyncYouTubeClient._delay()

                contents: list = YouTubeChannel.parse_nested_dicts(
                    ['appendContinuationItemsAction', 'continuationItems'],
                    continued_videos_data['onResponseReceivedActions'][0],
                    list
                )

            # Extract the rich video items and the continuation item
            *rich_items, continuation_item = contents

            # Loop through each video and log out its details
            for rich_item in rich_items:
                video_renderer: dict | None = \
                    YouTubeChannel.parse_nested_dicts(
                        ['richItemRenderer', 'content', 'videoRenderer'],
                        rich_item, dict
                    )

                video_id = video_renderer.get('videoId')
                if video_id:
                    video_ids.append(video_id)

            cont_renderer = continuation_item.get('continuationItemRenderer')
            if not cont_renderer:
                return video_ids

            # Extract the continuation token
            item_data: dict | None = YouTubeChannel.parse_nested_dicts(
                [
                    'continuationItemRenderer',
                    'continuationEndpoint',
                    'continuationCommand'
                ], continuation_item, dict
            )
            continuation_token = item_data['token']

        return video_ids

    async def scrape_video(
        self, video_id: str, table: Table,
        ingest_videos: bool, channel_thumbnail: YouTubeThumbnail | None
    ) -> YouTubeVideo | None:
        '''
        Find the videos in the by walking through the deserialized
        output of a scrape of a YouTube channel

        :param video_id: YouTube video ID
        :param video_table: Table to see if video has already been ingested
        where to store newly ingested videos
        :param ingest_videos: whether to upload the A/V streams of the
        scraped assets to storage
        :returns: the scraped YouTubeVideo or None if the video should not be
        ingested
        :raises: ByodaRuntimeError: if scraping the video fails
        '''

        log_data: dict[str, str] = {
            'channel': self.name, 'video_id': video_id
        }
        _LOGGER.debug('Processing video', extra=log_data)

        # We scrape if either:
        # 1: We haven't processed the video before
        # 2: We have already ingested the asset with ingest_status
        # 'external' and we now want to ingest the AV streams for the
        # channel
        status = IngestStatus.NONE

        data_filter: DataFilterSet = DataFilterSet(
            {'publisher_asset_id': {'eq': video_id}}
        )
        result: list[QueryResult] | None = await table.query(data_filter)
        if result and isinstance(result, list) and len(result):
            video_data, _ = result[0]
            try:
                status: IngestStatus | None = \
                    video_data.get('ingest_status')

                if isinstance(status, str):
                    status = IngestStatus(status)
            except ValueError:
                status = IngestStatus.NONE

            if not ingest_videos and status == IngestStatus.EXTERNAL:
                _LOGGER.debug(
                    'Skipping video as it is already ingested and we are '
                    'not importing AV streams', extra=log_data
                )
                return
            elif status == IngestStatus.PUBLISHED:
                _LOGGER.debug(
                    'Skipping video that we already ingested earlier in this '
                    'run', extra=log_data
                )
                return

            _LOGGER.debug(
                f'Ingesting AV streams video with ingest status {status}',
                extra=log_data
            )
        else:
            if ingest_videos:
                status = IngestStatus.NONE

        video: YouTubeVideo = await YouTubeVideo.scrape(
            video_id, ingest_videos, self.name, channel_thumbnail,
            browse_client=self.browse_client,
            download_client=self.download_client,
            storage_driver=self.storage_driver,
        )

        if not video:
            # This can happen if we decide not to import the video
            return

        if video.ingest_status != IngestStatus.UNAVAILABLE:
            # Video IDs may appear multiple times in scraped data
            # so we set the ingest status for the class instance
            # AND for the dict of already ingested videos
            video._transition_state(IngestStatus.QUEUED_START)

        return video

    @staticmethod
    async def get_channel(title: str) -> Self:
        '''
        Gets the channel ID using the YouTube innertube API
        '''

        channel = YouTubeChannel(title=title)

        return channel
