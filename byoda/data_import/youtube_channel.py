'''
Model a Youtube channel


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import re

from uuid import UUID
from uuid import uuid4
from typing import Self
from shutil import rmtree
from random import random
from tempfile import mkdtemp
from logging import getLogger
from datetime import UTC
from datetime import datetime

import orjson

from anyio import sleep
from bs4 import BeautifulSoup
from innertube import InnerTube
from httpx import AsyncClient as AsyncHttpClient

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

from byoda.util.api_client.api_client import HttpResponse

from byoda.util.test_tooling import convert_number_string

from byoda.util.logger import Logger

from .youtube_video import YouTubeVideo
from .youtube_thumbnail import YouTubeThumbnail

_LOGGER: Logger = getLogger(__name__)

# Limits the amount of videos imported for a channel
# per run
MAX_CHANNEL_VIDEOS_PER_RUN: int = 40


class YouTubeChannel:
    DATASTORE_CLASS_NAME: str = 'channels'
    SCRAPE_URL: str = 'https://www.youtube.com'
    CHANNEL_URL_WITH_AT: str = SCRAPE_URL + '/@{channel_name}/videos'
    CHANNEL_URL: str = SCRAPE_URL + '/{channel_name}'
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
    CHANNEL_DATACLASS: str = 'channels'

    def __init__(self, name: str = None, channel_id: str = None,
                 title: str | None = None, ingest: bool = False,
                 lock_file: str = None) -> None:
        '''
        Models a YouTube channel

        :param name: the name of the channel as it appears in the vanity URL,
        i.e., for https://www.youtube.com/@HistoryMatters, name is
        'HistoryMatters'
        :param channel_id: The YouTube channel ID, i.e. the last part of:
        https://www.youtube.com/channel/UC22BdTgxefuvUivrjesETjg
        :param ingest: whether to ingest the A/V streams of the scraped assets
        :param api_client: the optional YouTube data API client
        '''

        self.lock_file: str = lock_file

        self.channel_id: UUID | None = None

        self.name: str | None = name
        if self.name:
            self.name = name.lstrip('@')

        self.title: str | None = title

        self.youtube_channel_id: str | None = channel_id

        self.description: str | None = None
        self.keywords: list[str] = []
        self.is_family_safe: bool = False
        self.available_country_codes: list[str] = []
        self.channel_thumbnails: set[YouTubeThumbnail] = set()

        # This thumbnail is used for the YouTubeVideo.creator_thumbnail
        self.channel_thumbnail: YouTubeThumbnail | None = None

        self.banners: list[YouTubeThumbnail] = []
        self.external_urls: list[str] = []
        self.claims: list[Claim] = []

        # YouTube does not seem to keep these RSS feeds up to date
        self.rss_url: str | None = None

        # The number of subscribers and views are not always available
        self.youtube_subscribers_count: int | None = None
        self.youtube_videos_count: int | None = None
        self.youtube_views_count: int | None = None

        self.asset_ingest_enabled: bool = False
        self.ingest_videos: bool = ingest

        self.videos: dict[YouTubeVideo] = {}

    def as_dict(self) -> dict[str, any]:
        data: dict[str, any] = {
            'created_timestamp': datetime.now(tz=UTC),
            'channel_id': self.channel_id,
            'creator': self.name.lstrip('@'),
            'description': self.description,
            'is_family_safe': self.is_family_safe,
            'available_counter_codes': self.available_country_codes,
            'channel_thumbnails': [
                t.as_dict() for t in self.channel_thumbnails
            ],
            'banners': [t.as_dict() for t in self.banners],
            'external_urls': self.external_urls,
            'thirdparty_platform_followers':
                self.youtube_subscribers_count or 0,
            'thirdparty_platform_videos': self.youtube_videos_count or 0,
            'thirdparty_platform_views': self.youtube_views_count or 0,
            'claims': []
        }

        return data

    def update_lock_file(self) -> None:
        '''
        We update the lock file every time we do something so
        we can be more aggressive with removing stale lock files
        '''

        with open(self.lock_file, 'w') as lock_file:
            lock_file.write('1')

    async def persist_channel_info(self, member: Member, data_store: DataStore,
                                   storage_driver: FileStorage,
                                   custom_domain: str | None = None) -> None:
        '''
        Persist the creator thumbnails and banners to storage

        :param member:
        :param data_store:
        :param storage_driver:
        :param custom_domain: what hostname should be used in content URLs if
        no CDN is used
        '''

        log_data: dict[str, str] = {'channel': self.name}

        _LOGGER.debug('Persisting channel', extra=log_data)

        table: ArraySqlTable = data_store.get_table(
            member.member_id, YouTubeChannel.CHANNEL_DATACLASS
        )
        data_filter: DataFilterSet = DataFilterSet(
            {'creator': {'eq': self.name}}
        )

        channel_data: dict[str, any] = self.as_dict()
        cursor: str = table.get_cursor_hash(channel_data, member.member_id)

        rows: list[QueryResult] | None = await table.query(
            data_filters=data_filter
        )
        if not rows:
            _LOGGER.debug(
                'Creator is not yet in the data store',
                extra=log_data
            )

            channel_id: UUID = uuid4()

            dirpath: str = mkdtemp(dir='/tmp')
            thumbnail: YouTubeThumbnail
            for thumbnail in self.channel_thumbnails:
                await thumbnail.ingest(
                    video_id=channel_id, storage_driver=storage_driver,
                    member=member, work_dir=dirpath,
                    custom_domain=custom_domain
                )

            for thumbnail in self.banners:
                await thumbnail.ingest(
                    video_id=channel_id, storage_driver=storage_driver,
                    member=member, work_dir=dirpath,
                    custom_domain=custom_domain
                )

            rmtree(dirpath)

            await table.append(
                channel_data, cursor, origin_id=None,
                origin_id_type=None, origin_class_name=None
            )
            _LOGGER.debug('Created channel in the data store', extra=log_data)
        else:
            data: dict[str, any] = {
                'thirdparty_platform_followers':
                    self.youtube_subscribers_count,
                'thirdparty_platform_views': self.youtube_views_count,
            }
            await table.update(
                data, cursor, data_filter, None, None, None,
                placeholder_function=PostgresStorage.get_named_placeholder
            )
            log_data['thirdparty_platform_followers'] = \
                self.youtube_subscribers_count
            log_data['thirdparty_platform_views'] = self.youtube_views_count
            _LOGGER.info('Updated channel followers and views', extra=log_data)

        return None

    async def scrape(
        self, member: Member, data_store: DataStore,
        storage_driver: FileStorage, video_table: Table,
        bento4_directory: str | None = None,
        moderate_request_url: str | None = None,
        moderate_jwt_header: str | None = None,
        moderate_claim_url: str | None = None, ingest_interval: int = 0,
        custom_domain: str | None = None,
        max_videos_per_channel: int = 0,
    ) -> None:
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
        '''

        log_extra: dict[str, str] = {'channel': self.name}

        if not self.name:
            _LOGGER.warning('No channel name provided', extra=log_extra)
            return None

        page_data: str = await self.get_videos_page()

        if not page_data:
            _LOGGER.warning('No page data found for channel', extra=log_extra)
            return None

        self.parse_channel_info(page_data)

        await self.persist_channel_info(
            member, data_store, storage_driver, custom_domain=custom_domain
        )

        self.video_ids: list[str] = []
        try:
            self.video_ids = await self.get_video_ids()
        except Exception as exc:
            _LOGGER.info(
                f'Extracting video_ids failed: {exc}', extra=log_extra
            )
            return None

        videos_imported: int = 0
        for video_id in self.video_ids:
            video: YouTubeVideo = await self.scrape_video(
                video_id, video_table, self.ingest_videos,
                self.channel_thumbnail
            )

            if not video:
                continue

            log_extra['video_id'] = video.video_id
            log_extra['ingest_status'] = video.ingest_status.value

            if self.lock_file:
                self.update_lock_file()

            if video.channel_creator != self.name:
                _LOGGER.debug(
                    f'Video created by {video.channel_creator} does not '
                    f'belong to channel {self.name}', extra=log_extra
                )
                # By importing the asset with status unavailable, we prevent
                # attempts to ingest this asset again in future runs
                video._transition_state(IngestStatus.UNAVAILABLE)

            _LOGGER.debug('Persisting video', extra=log_extra)
            try:
                result: bool | None = await video.persist(
                    member, storage_driver,
                    self.ingest_videos, video_table,
                    bento4_directory,
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

            except Exception as exc:
                _LOGGER.warning(
                    f'Could not persist video: {exc}', extra=log_extra
                )

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

        return None

    async def get_videos_page(self) -> str:
        '''
        Get the videos page for the channel

        :returns: the text of the page
        '''

        log_data: dict[str, str] = {'channel': self.name}

        headers: dict[str, str] = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/112.0.0.0 Safari/537.36'
            )
        }
        async with AsyncHttpClient(headers=headers, follow_redirects=True
                                   ) as client:
            channel_name: str = self.name.lstrip('@').replace(' ', '')
            url: str = YouTubeChannel.CHANNEL_URL_WITH_AT.format(
                channel_name=channel_name
            )
            resp: HttpResponse = await client.get(url)

            if resp.status_code != 200:
                _LOGGER.warning(
                    f'HTTP scrape for {url} failed: {resp.status_code}',
                    extra=log_data
                )
                return

            await YouTubeChannel._delay()

        page_data: str = resp.text

        return page_data

    def parse_channel_info(self, page_data: str) -> None:
        '''
        Parses the info for the channel from the channel 'videos' page

        :param page_data: the text of the 'videos' page for the channel
        :returns: (none)
        '''

        log_data: dict[str, str] = {'channel': self.name}

        if not page_data:
            _LOGGER.warning('No page data to parse channel info from')
            return None

        self.youtube_channel_id: str = YouTubeChannel.extract_channel_id(
            page_data
        )

        parsed_data: dict[str, any] = YouTubeChannel.parse_scrape_data(
            self.youtube_channel_id, page_data
        )

        self.external_urls: list[dict[str, int | str]] = \
            YouTubeChannel.parse_external_urls(
                parsed_data
            )

        self.channel_thumbnails = (
            self.channel_thumbnails |
            YouTubeChannel.parse_thumbnails(parsed_data)
        )

        if self.channel_thumbnails:
            self.channel_thumbnail = sorted(
                self.channel_thumbnails, key=lambda k: k.height
            )[-1]

        self.banners: list[YouTubeThumbnail] = YouTubeChannel.parse_banners(
            parsed_data
        )

        self.youtube_subscribers_count = \
            YouTubeChannel.parse_subscriber_count(parsed_data)

        self.youtube_videos_count = \
            YouTubeChannel.parse_video_count(parsed_data)

        self.youtube_views_count = \
            YouTubeChannel.parse_views_count(parsed_data)

        channel_info: dict[str, any] = YouTubeChannel.parse_nested_dicts(
            ['metadata', 'channelMetadataRenderer'], parsed_data, dict
        )
        if not channel_info:
            _LOGGER.info(
                'No channel metadata found for channel', extra=log_data
            )
            return None

        self.name: str = channel_info.get('title', self.name)

        if self.name:
            self.name = self.name.lstrip('@')

        self.title = self.name
        self.description = channel_info.get('description', self.description)

        keywords: list[str] = channel_info.get('keywords')
        if keywords:
            self.keywords = keywords.split(',')

        self.is_family_safe = channel_info.get('isFamilySafe', False)

    @staticmethod
    def extract_channel_id(page_data: str) -> str:
        if not page_data:
            _LOGGER.warning('No page data to extract channel ID from')

        match: re.Match[str] | None = \
            YouTubeChannel.RX_SCRAPE_CHANNEL_ID.search(page_data)

        if match is None:
            raise ValueError('Channel ID not found')

        channel_id: str = match.group(1)

        return channel_id

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

    def parse_video_count(data: dict) -> int | None:
        '''
        Parse the video count from the scraped data

        :param data: the scraped data
        :returns: the subscriber count
        '''

        try:
            videos_data: dict | any = YouTubeChannel.parse_nested_dicts(
                [
                    'header', 'c4TabbedHeaderRenderer', 'videosCountText',
                    'runs'
                ], data, list
            )
            if not videos_data:
                return None

            youtube_video_count: int = convert_number_string(
                videos_data[0]['text']
            )

            return youtube_video_count
        except Exception as exc:
            _LOGGER.debug(f'Failed to parse video count: {exc}')
            return None

    def parse_subscriber_count(data: dict) -> int | None:
        '''
        Parse the subscriber count from the scraped data

        :param data: the scraped data
        :returns: the subscriber count
        '''

        try:
            subs_text: str | any = YouTubeChannel.parse_nested_dicts(
                [
                    'header', 'c4TabbedHeaderRenderer',
                    'subscriberCountText', 'simpleText'
                ], data, str
            )
            if not subs_text:
                return None

            youtube_subs_count: int | None = convert_number_string(subs_text)

            return youtube_subs_count
        except Exception as exc:
            _LOGGER.debug(f'Failed to parse subscriber count: {exc}')
            return None

    def parse_views_count(data: dict) -> int | None:
        '''
        Parse the video count from the scraped data

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

            youtube_views_count: int | None = convert_number_string(views_data)

            return youtube_views_count
        except Exception as exc:
            _LOGGER.debug(f'Failed to parse views count: {exc}')
            return None

    @staticmethod
    def parse_thumbnails(data: dict[str, any]) -> set[YouTubeThumbnail]:
        '''
        Parses the thumbnails out of the YouTube channel page either
        scraped or retrieved using the InnerTube API
        '''

        # First we try to get data from the channel scrape:
        thumbnails_data: list | None = YouTubeChannel.parse_nested_dicts(
            [
                'header', 'c4TabbedHeaderRenderer', 'avatar', 'thumbnails'
            ], data, list
        )
        if not thumbnails_data:
            # Now we try to get the data from the InnerTube API
            if ('thumbnail' not in data
                    or not isinstance(data['thumbnail'], dict)):
                return set()

            if ('thumbnails' not in data['thumbnail']
                    or not isinstance(data['thumbnail']['thumbnails'], list)):
                return set()
            thumbnails_data = data['thumbnail']['thumbnails']

        channel_thumbnails: set[YouTubeThumbnail] = set()
        for thumbnail_data in thumbnails_data:
            url: str | None = thumbnail_data.get('url')
            if (url and (
                    not url.startswith('https://') or url.startswith('//'))):
                thumbnail_data['url'] = f'https:{url}'
            thumbnail = YouTubeThumbnail(None, thumbnail_data)
            channel_thumbnails.add(thumbnail)

        return channel_thumbnails

    @staticmethod
    def parse_external_urls(data: dict[str, any]) -> list[str]:
        '''
        Parses the external URLs out of the YouTube channel page

        :param data: the YouTube channel page as a dict
        :returns: list of external URLs
        '''

        external_links: list[str] = []

        channel_url: str = YouTubeChannel.parse_nested_dicts(
            ['metadata', 'channelMetadataRenderer', 'vanityChannelUrl'], data,
            str
        )
        url: str | None = None
        if channel_url:
            url = channel_url
        else:
            channel_urls: list[str] = YouTubeChannel.parse_nested_dicts(
                [
                    'metadata', 'channelMetadataRenderer', 'ownerUrls'
                ], data, list
            )
            if channel_urls and isinstance(channel_urls, list):
                url = channel_urls[0]

        if url:
            if url.startswith('http://'):
                url = f'https://{url[len("http://"):]}'

            external_links.append(
                {'priority': 0, 'name': 'YouTube', 'url': url}
            )

        links_data: dict[str, dict[str, any]] = \
            YouTubeChannel.parse_nested_dicts(
                [
                    'header', 'c4TabbedHeaderRenderer', 'headerLinks',
                    'channelHeaderLinksViewModel',
                ], data, dict
            )

        if links_data:
            priority: int = 10
            for link_data in links_data.values():
                link: dict[str, str | int] | None = \
                    YouTubeChannel._generate_external_link(link_data, priority)

                if link:
                    external_links.append(link)
                    priority += 10

        return external_links

    @staticmethod
    def _generate_external_link(link_data: dict, priority: int
                                ) -> dict[str, str | int] | None:
        url: str | None = link_data.get('content')

        if not url:
            return None

        # Strip of the protocol from the url
        if url.startswith('http://'):
            url = url[len('http://'):]
        elif url.startswith('https://'):
            url = url[len('https://'):]

        # Let's try to figure out with social network the url is pointing to
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
                return
            else:
                _LOGGER.debug(f'Could not parse link name our of URL: {url}')
                name = url

        name = SocialNetworks.get(name.lower(), 'www')

        _LOGGER.debug(f'Parsed external link label {name} ouf of {url}')
        return {
            'priority': priority, 'name': name, 'url': f'https://{url}'
        }

    @staticmethod
    def parse_banners(data: dict[str, any]) -> list[YouTubeThumbnail]:
        '''
        Parses the banner images out of the YouTube channel page

        :param data: the YouTube channel page as a dict
        :returns: list of banners as YouTubeThumbnails
        '''

        banners: list[YouTubeThumbnail] = []

        banner_type: str
        for banner_type in ['banner', 'tvBanner', 'mobileBanner']:
            banner_data: dict[str, str | int] = \
                YouTubeChannel.parse_nested_dicts(
                    [
                        'header', 'c4TabbedHeaderRenderer', banner_type,
                        'thumbnails'
                    ], data, list
                )

            thumbnail_data: dict[str, str | int]
            for thumbnail_data in banner_data or []:
                channel_banner: YouTubeThumbnail = YouTubeThumbnail(
                    None, thumbnail_data, display_hint=banner_type
                )
                _LOGGER.debug(f'Found banner: {channel_banner.url}')
                banners.append(channel_banner)

        return banners

    @staticmethod
    def parse_scrape_data(channel_id: str, page_data: str) -> dict[str, any]:
        '''
        Parse the channel scrape data

        :param data: the data to parse
        :returns: the parsed data
        '''

        soup = BeautifulSoup(page_data, 'html.parser')
        script: str = soup.find(
            'script', string=YouTubeChannel.CHANNEL_SCRAPE_REGEX_SHORT
        ).text

        if not script:
            _LOGGER.warning('Did not find text in HTML scrape')
            soup = None
            script = None
            return {}

        parsed_data: dict[str, any] = {}

        raw_data: str = YouTubeChannel.CHANNEL_SCRAPE_REGEX.search(
            script
        ).group(1)

        try:
            parsed_data: dict[str, any] = orjson.loads(raw_data)
        except orjson.JSONDecodeError as exc:
            _LOGGER.debug(
                f'Failed parsing JSON data for channel {channel_id}: '
                f'{exc}'
            )
            return {}

        # Make sure memory is released
        soup.decompose()
        soup = None
        raw_data = None
        script = None

        return parsed_data

    @staticmethod
    def parse_nested_dicts(keys: list[str], data: dict[str, any],
                           final_type: callable) -> object | None:
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

                videos_tab_renderer = tabs[1]['tabRenderer']

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
                await YouTubeChannel._delay()

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
                await YouTubeChannel._delay()

                contents: list = YouTubeChannel.parse_nested_dicts(
                    ['appendContinuationItemsAction', 'continuationItems'],
                    continued_videos_data['onResponseReceivedActions'][0],
                    list
                )

            # Extract the rich video items and the continuation item
            *rich_items, continuation_item = contents

            # Loop through each video and log out its details
            for rich_item in rich_items:
                video_renderer: dict = YouTubeChannel.parse_nested_dicts(
                    ['richItemRenderer', 'content', 'videoRenderer'],
                    rich_item, dict
                )
                video_id = video_renderer['videoId']
                video_ids.append(video_id)

            cont_renderer = continuation_item.get('continuationItemRenderer')
            if not cont_renderer:
                return video_ids

            # Extract the continuation token
            item_data: dict = YouTubeChannel.parse_nested_dicts(
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
        ingest_videos: bool, creator_thumbnail: YouTubeThumbnail | None
    ) -> YouTubeVideo | None:
        '''
        Find the videos in the by walking through the deserialized
        output of a scrape of a YouTube channel

        :param video_id: YouTube video ID
        :param video_table: Table to see if video has already been ingested
        where to store newly ingested videos
        :param ingest_videos: whether to upload the A/V streams of the
        scraped assets to storage
        '''

        log_data: dict[str, str] = {
            'channel': self.name,
            'video_id': video_id
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
                return None
            elif status == IngestStatus.PUBLISHED:
                _LOGGER.debug(
                    'Skipping video that we already ingested earlier in this '
                    'run', extra=log_data
                )
                return None

            _LOGGER.debug(
                f'Ingesting AV streams video with ingest status {status}',
                extra=log_data
            )
        else:
            if ingest_videos:
                status = IngestStatus.NONE

        video: YouTubeVideo = await YouTubeVideo.scrape(
            video_id, ingest_videos, self.name, creator_thumbnail
        )

        if not video:
            # This can happen if we decide not to import the video
            return None

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

    @staticmethod
    async def _delay(min: int = 2, max: int = 5) -> None:
        await sleep(random() * (max - min) + min)
