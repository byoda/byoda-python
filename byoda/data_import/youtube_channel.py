'''
Model a Youtube channel


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
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
from datetime import timedelta

import orjson

from anyio import sleep
from bs4 import BeautifulSoup
from innertube import InnerTube
from httpx import AsyncClient as AsyncHttpClient

from googleapiclient.discovery import Resource as YouTubeResource

from byoda.datamodel.claim import Claim
from byoda.datamodel.member import Member
from byoda.datamodel.table import QueryResult
from byoda.datamodel.sqltable import ArraySqlTable
from byoda.datamodel.datafilter import DataFilterSet

from byoda.datatypes import SocialNetworks
from byoda.datatypes import IngestStatus

from byoda.datastore.data_store import DataStore

from byoda.storage.filestorage import FileStorage

from byoda.util.api_client.api_client import HttpResponse

from byoda.exceptions import ByodaRuntimeError

from byoda.util.logger import Logger
from byoda.util.test_tooling import convert_number_string

from .youtube_video import YouTubeVideo
from .youtube_thumbnail import YouTubeThumbnail

_LOGGER: Logger = getLogger(__name__)


class YouTubeChannel:
    DATASTORE_CLASS_NAME: str = 'channels'
    SCRAPE_URL: str = 'https://www.youtube.com'
    CHANNEL_URL_WITH_AT: str = SCRAPE_URL + '/@{channel_name}'
    CHANNEL_URL: str = SCRAPE_URL + '/{channel_name}'
    CHANNEL_VIDEOS_URL: str = SCRAPE_URL + '/channel/{channel_id}/videos'
    CHANNEL_SCRAPE_REGEX_SHORT: re.Pattern[str] = re.compile(
        r'var ytInitialData = (.*?);'
    )
    CHANNEL_SCRAPE_REGEX: re.Pattern[str] = re.compile(
        r'var ytInitialData = (.*?);$'
    )
    CHANNEL_DATACLASS: str = 'channels'

    def __init__(self, name: str = None, channel_id: str = None,
                 title: str | None = None, ingest: bool = False,
                 api_client: YouTubeResource = None) -> None:
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

        self.name: str | None = name
        if self.name:
            self.name = name.lstrip('@')

        self.channel_id: str | None = channel_id

        # e.g. 'History Matters'
        self.title: str | None = title

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
        self.subs_count: int | None = None
        self.views_count: int | None = None

        self.asset_ingest_enabled: bool = False
        self.ingest_videos: bool = ingest
        self.api_client: YouTubeResource | None = api_client

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
            'claims': []
        }

        return data

    async def persist(self, member: Member, data_store: DataStore,
                      storage_driver: FileStorage,
                      already_ingested_videos: dict[str, dict] = {},
                      bento4_directory: str | None = None,
                      moderate_request_url: str | None = None,
                      moderate_jwt_header: str | None = None,
                      moderate_claim_url: str | None = None,
                      ingest_interval: int = 0,
                      custom_domain: str | None = None) -> None:
        '''
        persist any video not yet in the public_assets collection to that
        collection, including downloading the video, packaging it, and
        saving it to the file store
        '''

        await self.persist_channel(
            member, data_store, storage_driver, custom_domain=custom_domain
        )

        # The strategy here is simple: we try to store all videos. persist()
        # first checks whether the video is already in the data store and only
        # adds it if it is not. If the asset exists and has ingest status
        # 'external' and this channel is configured to download AV tracks
        # then the existing asset will be updated
        video: YouTubeVideo | None
        for video in self.videos.values():
            _LOGGER.debug(
                f'Persisting video {video.video_id} for channel {self.name}'
            )
            try:
                result: bool | None = await video.persist(
                    member, storage_driver,
                    self.ingest_videos, already_ingested_videos,
                    bento4_directory,
                    moderate_request_url=moderate_request_url,
                    moderate_jwt_header=moderate_jwt_header,
                    moderate_claim_url=moderate_claim_url,
                    custom_domain=custom_domain
                )

                if result is None:
                    _LOGGER.debug(f'Failed to persist video {video.video_id}')

                if ingest_interval:
                    random_delay: float = \
                        random() * ingest_interval + ingest_interval / 2
                    await sleep(random_delay)
            except (ValueError, ByodaRuntimeError) as exc:
                _LOGGER.exception(
                    f'Could not persist video {video.video_id}: {exc}'
                )

            video = None

        self.videos = []

    async def persist_channel(self, member: Member, data_store: DataStore,
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

        table: ArraySqlTable = data_store.get_table(
            member.member_id, YouTubeChannel.CHANNEL_DATACLASS
        )
        data_filter: DataFilterSet = DataFilterSet(
            {'creator': {'eq': self.name}}
        )
        rows: list[QueryResult] | None = await table.query(
            data_filters=data_filter
        )

        if rows:
            _LOGGER.debug(f'Creator {self.name} already in the data store')
            return None

        self.channel_id: UUID = uuid4()

        dirpath: str = mkdtemp(dir='/tmp')
        thumbnail: YouTubeThumbnail
        for thumbnail in self.channel_thumbnails:
            await thumbnail.ingest(
                video_id=self.channel_id, storage_driver=storage_driver,
                member=member, work_dir=dirpath, custom_domain=custom_domain
            )

        for thumbnail in self.banners:
            await thumbnail.ingest(
                video_id=self.channel_id, storage_driver=storage_driver,
                member=member, work_dir=dirpath
            )

        rmtree(dirpath)

        channel_data: dict[str, any] = self.as_dict()
        cursor: str = table.get_cursor_hash(channel_data, member.member_id)
        await table.append(
            channel_data, cursor, origin_id=None,
            origin_id_type=None, origin_class_name=None
        )
        _LOGGER.debug(f'Created channel for {self.name} in the data store')

        return None

    async def scrape(self, already_ingested_videos: dict[str, dict] = {},
                     filename: str = None) -> None:
        '''
        Scrapes videos from the YouTube website and optionally stores them in
        the data store

        :param already_ingested_videos: dictionary of ingested assets with
        YouTube video IDs as keys and as values the data from the member data
        store
        :param filename: file with scrape data. If not specified, the data is
        retrieved from the youtube.com website.
        :returns: number of pages scraped
        '''

        self.get_channel_data()

        if filename:
            with open(filename, 'r') as file_desc:
                data: str = file_desc.read()
        else:
            headers: dict[str, str] = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/112.0.0.0 Safari/537.36'
                )
            }
            async with AsyncHttpClient(headers=headers, follow_redirects=True
                                       ) as client:
                url: str = YouTubeChannel.CHANNEL_URL_WITH_AT.format(
                    channel_name=self.name.lstrip('@')
                ).replace(' ', '')

                _LOGGER.debug(f'Scraping YouTube channel at {url}')
                resp: HttpResponse = await client.get(url)
                if resp.status_code != 200:
                    _LOGGER.warning(
                        f'HTTP scrape for {url} failed: {resp.status_code}'
                    )
                    return

                data = resp.text

        parsed_data: dict[str, any] = YouTubeChannel.parse_scrape_data(
            self.channel_id, data
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

        channel_info: dict[str, any] = YouTubeChannel.parse_nested_dicts(
            ['metadata', 'channelMetadataRenderer'], parsed_data, dict
        )
        if not channel_info:
            _LOGGER.info(f'No channel metadata found for channel {self.name}')
            return None

        self.name: str = channel_info.get('title', self.name)

        if self.name:
            self.name = self.name.lstrip('@')

        self.description = channel_info.get('description', self.description)

        keywords: list[str] = channel_info.get('keywords')
        if keywords:
            self.keywords = keywords.split(',')

        self.is_family_safe = channel_info.get('isFamilySafe', False)
        await self.find_videos(
            parsed_data, already_ingested_videos, self.ingest_videos,
            self.channel_thumbnail
        )

        _LOGGER.debug(
            f'Scraped {len(self.videos)} videos from '
            f'YouTube channel {self.name}'
        )

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
            url = url[len("http://"):]
        elif url.startswith('https://'):
            url = url[len("https://"):]

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
        script = soup.find(
            'script', string=YouTubeChannel.CHANNEL_SCRAPE_REGEX_SHORT
        )

        if not script:
            _LOGGER.warning('Did not find text in HTML scrape')
            soup = None
            script = None
            return {}

        parsed_data: dict[str, any] = {}

        raw_data: str = YouTubeChannel.CHANNEL_SCRAPE_REGEX.search(
            script.text
        ).group(1)

        try:
            parsed_data: dict[str, any] = orjson.loads(raw_data)
        except orjson.JSONDecodeError as exc:
            _LOGGER.debug(
                f'Failed parsing JSON data for channel {channel_id}: '
                f'{exc}'
            )
            return {}

        raw_data = None
        soup = None
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

    async def find_videos(self, data: dict | list | int | str | float,
                          already_ingested_videos: dict[str, dict],
                          ingest_videos: bool,
                          creator_thumbnail: YouTubeThumbnail | None) -> None:
        '''
        Find the videos in the by walking through the deserialized
        output of a scrape of a YouTube channel

        :param data: a subset of the scraped data from youtube.com
        :param already_ingested_videos: assets already in the member DB
        :param ingest_videos: whether to upload the A/V streams of the
        scraped assets to storage
        '''

        if isinstance(data, list):
            for item in data:
                if type(item) in (dict, list):
                    await self.find_videos(
                        item, already_ingested_videos, ingest_videos,
                        creator_thumbnail
                    )

        if not isinstance(data, dict):
            return

        video_id: str | None = data.get('videoId')

        if not video_id:
            for value in data.values():
                if type(value) in (dict, list):
                    await self.find_videos(
                        value, already_ingested_videos, self.ingest_videos,
                        creator_thumbnail
                    )

            return

        _LOGGER.debug(f'Processing video {video_id}')

        # We scrape if either:
        # 1: We haven't processed the video before
        # 2: We have already ingested the asset with ingest_status
        # 'external' and we now want to ingest the AV streams for the
        # channel
        status = IngestStatus.NONE

        if video_id in already_ingested_videos:
            try:
                status: IngestStatus | None = \
                    already_ingested_videos[video_id].get('ingest_status')

                if isinstance(status, str):
                    status = IngestStatus(status)
            except ValueError:
                status = IngestStatus.NONE

            if not ingest_videos and status == IngestStatus.EXTERNAL:
                _LOGGER.debug(
                    f'Skipping video {video_id} as it is already '
                    'ingested and we are not importing AV streams'
                )
                # We don't need to keep all the info for the video in memory
                # if we don't plan on ingesting it
                already_ingested_videos[video_id] = {'ingest_status': status}
                return
            elif status == IngestStatus.PUBLISHED:
                _LOGGER.debug(
                    f'Skipping video {video_id} that we already ingested '
                    'earlier in this run'
                )
                # We don't need to keep all the info for the video in memory
                # if we don't plan on ingesting it
                already_ingested_videos[video_id] = {'ingest_status': status}
                return

            _LOGGER.debug(
                f'Ingesting AV streams video {video_id} '
                f'with ingest status {status}'
            )
        else:
            if ingest_videos:
                status = IngestStatus.NONE

        video = await YouTubeVideo.scrape(
            video_id, ingest_videos, creator_thumbnail
        )

        if not video:
            # This can happen if we decide not to import the video
            return

        # Video IDs may appear multiple times in scraped data
        # so we set the ingest status for the class instance
        # AND for the dict of already ingested videos
        video._transition_state(IngestStatus.QUEUED_START)

        if video_id not in already_ingested_videos:
            already_ingested_videos[video_id] = {}
        already_ingested_videos[video_id]['ingest_status'] = \
            video.ingest_status

        self.videos[video_id] = video

    def get_channel_id(self) -> None:
        '''
        Gets the channel ID using the YouTube Data API
        '''

        if not self.api_client:
            raise RuntimeError(
                'instance not set up for calling YouTube data API'
            )
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

    def get_channel_data(self) -> None:
        '''
        Gets the channel data using the YouTube innertube API
        '''

        client = InnerTube('WEB')
        search: str = self.name or self.title
        if not search:
            raise ValueError('No channel name or title to search for')

        data: dict = client.search(query=search)

        # Reduce memory usage
        client = None

        contents: object | None = YouTubeChannel.parse_nested_dicts(
            [
                'contents', 'twoColumnSearchResultsRenderer',
                'primaryContents', 'sectionListRenderer',
                'contents',
            ], data, list
        )

        for item in contents:
            results: object | None = YouTubeChannel.parse_nested_dicts(
                [
                    'itemSectionRenderer', 'contents',
                ], item, list
            )
            for result in results or []:
                channel_data: dict[str, any] = result.get('channelRenderer')
                if not channel_data:
                    continue

                self.parse_channel_data(channel_data)

                # No need to parse more than 1 search result
                return

    def parse_channel_data(self, channel_data: dict[str, any]) -> None:
        '''
        Parses the 'channelRenderer' data from the YouTube innertube API

        :param channel_data: the 'channelRenderer' data returned by the
        YouTube innertube search API
        '''

        self.channel_id = channel_data.get('channelId')
        self.title = channel_data['title'].get('simpleText')
        description_data: list | None = YouTubeChannel.parse_nested_dicts(
            ['descriptionSnippet', 'runs'], channel_data, list
        )
        if description_data and len(description_data):
            self.description = description_data[0].get('text')
            if len(description_data) > 1:
                self.description += description_data[1].get('text')

        url: str = YouTubeChannel.parse_nested_dicts(
            [
                'navigationEndpoint', 'commandMetadata',
                'webCommandMetadata', 'url',
            ], channel_data, str
        )
        url = url.lstrip('/')
        if not self.name:
            self.name = url.lstrip('@')

        self.channel_thumbnails = (
            self.channel_thumbnails |
            YouTubeChannel.parse_thumbnails(channel_data)
        )

        subs_count_text: str | None = \
            YouTubeChannel.parse_nested_dicts(
                ['videoCountText', 'simpleText'], channel_data, str
            )
        if subs_count_text:
            self.subs_count = convert_number_string(
                subs_count_text.rstrip(' subscribers')
            )

    @staticmethod
    def get_channel(title: str) -> Self:
        '''
        Gets the channel ID using the YouTube innertube API
        '''

        channel = YouTubeChannel(title=title)
        channel.get_channel_data()
        return channel

    async def import_videos(self, already_ingested_videos: dict[str, str],
                            max_api_requests: int = 1000) -> None:
        '''
        Imports the videos from the YouTube data API. It processes the newest
        videos first and skips any videos that are already imported

        :param already_ingested_videos: a dictionary with the video ID as key
        and the encoding status as value
        :param max_api_requests: the maximum number of API requests to make
        '''

        api_requests: int = 0

        if not self.channel_id:
            self.get_channel_id()
            api_requests += 1

        # The YouTube Data API can only sort by newest videos first
        # So our strategy is:
        # 1: get the videos newer than the newest video we've already ingested
        # 2: get the videos older than the oldest video we've already ingested

        # 1: get videos newer than what have already ingested or, if we
        # haven't ingested any videos yet all videos, # newer than 1970
        published_timestamp: datetime = datetime(
            1970, 1, 1, tzinfo=UTC
        )

        if already_ingested_videos:
            published_timestamp = max(
                [
                    asset['published_timestamp']
                    for asset in already_ingested_videos.values()
                ]
            )
            published_timestamp += timedelta(seconds=1)

        page_token: str | None = None
        while api_requests + 100 < max_api_requests:
            request = self.api_client.search().list(
                order='date', maxResults=50, pageToken=page_token,
                publishedAfter=published_timestamp.isoformat(),
                channelId=self.channel_id, type='video',
                part="id, snippet",

            )
            response: dict
            retries: int
            response, retries = await self._call_api(request)
            # Search API of YouTube Data API consumes 100 credits per call
            api_requests += 100 + retries

            if not response:
                return

            await self._import_video_data(
                response.get('items', []), already_ingested_videos
            )

            page_token: str = response.get('nextPageToken')
            if not page_token:
                _LOGGER.debug('Reached end of channel video pagination')
                break

        # 2: get videos older than what we already have
        if already_ingested_videos:
            published_timestamp = min(
                [
                    asset['published_timestamp']
                    for asset in already_ingested_videos.values()
                ]
            ) - timedelta(seconds=1)
            page_token: str | None = None
            while api_requests < max_api_requests:
                request = self.api_client.search().list(
                    order='date', maxResults=50, pageToken=page_token,
                    publishedBefore=published_timestamp.isoformat(),
                    channelId=self.channel_id, type='video',
                    part="id, snippet",

                )
                response, retries = await self._call_api(request)
                # Search API of YouTube Data API consumes 100 credits per call
                api_requests += 100 + retries

                if not response:
                    return

                await self._import_video_data(
                    response.get('items', []), already_ingested_videos
                )

                page_token: str = response.get('nextPageToken')
                if not page_token:
                    _LOGGER.debug('Reached end of channel video pagination')
                    break

        self.api_client.close()

        _LOGGER.debug(
            f'Performed {api_requests} API requests against '
            f'a max of {max_api_requests} for channel {self.name}'
        )

    async def _import_video_data(self, data: dict,
                                 already_ingested_videos: dict[str, str],
                                 ) -> None:
        '''
        Parse the data returned by the YouTube Data Search API

        :param data: the 'items' data as returned by the YouTube Data Search
        API
        :param already_ingested_videos: a dictionary with the video ID as key
        and the encoding status as value
        :returns: number of imported videos
        '''

        for video_data in data:
            video_id: str = YouTubeVideo.get_video_id_from_api(video_data)
            published_at: datetime = \
                YouTubeVideo.get_publish_datetime_from_api(video_data)

            if video_id in already_ingested_videos:
                ingest_status = already_ingested_videos[video_id].get(
                    'ingest_status'
                )
                if isinstance(ingest_status, str):
                    ingest_status = IngestStatus(ingest_status)
            else:
                ingest_status = IngestStatus.NONE

            if (video_id in already_ingested_videos and (
                    not self.ingest_videos or ingest_status != 'external')):
                continue

            video: YouTubeVideo = YouTubeVideo.scrape(
                video_id, already_ingested_videos, None
            )
            video.published_time = published_at

            self.videos[video.video_id] = video

    async def _call_api(self, request: dict) -> tuple[dict, int]:
        '''
        Calls the YouTube data API with the given request

        :param request: the request to call the API with
        :returns: the response from the API
        '''

        if not self.api_client:
            raise RuntimeError(
                'instance not set up for calling YouTube data API'
            )

        retries: int = 0
        max_retries: int = 3
        retry_delay: list[int] = [0, 10, 180, 1800]
        while retries < max_retries:
            delay = retry_delay[retries]
            if delay:
                _LOGGER.debug(f'Retry {retries}, delaying {delay} seconds')
                await sleep(retry_delay[retries])

            try:
                response = request.execute()
                return response, retries
            except Exception as exc:
                retries += 1
                _LOGGER.debug(
                    f'YouTube Data API call failed, try {retries}: {exc}'
                )

        _LOGGER.debug(f'Max retries exceeded: {retries} of {max_retries}')
        return None, retries
