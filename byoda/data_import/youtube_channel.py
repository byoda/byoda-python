'''
Model a Youtube channel


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import re

from random import random
from logging import getLogger
from datetime import datetime
from datetime import timezone, timedelta

import orjson

from anyio import sleep

from httpx import AsyncClient as AsyncHttpClient

from bs4 import BeautifulSoup

from googleapiclient.discovery import Resource as YouTubeResource

from byoda.datamodel.member import Member

from byoda.datatypes import IngestStatus

from byoda.storage.filestorage import FileStorage

from byoda.util.api_client.api_client import HttpResponse

from byoda.exceptions import ByodaRuntimeError

from byoda.util.logger import Logger

from .youtube_video import YouTubeVideo
from .youtube_thumbnail import YouTubeThumbnail

_LOGGER: Logger = getLogger(__name__)


class YouTubeChannel:
    SCRAPE_URL: str = 'https://www.youtube.com'
    CHANNEL_URL_WITH_AT: str = SCRAPE_URL + '/@{channel_name}'
    CHANNEL_URL: str = SCRAPE_URL + '/{channel_name}'
    CHANNEL_VIDEOS_URL: str = SCRAPE_URL + '/channel/{channel_id}/videos'
    CHANNEL_SCRAPE_REGEX = re.compile(r'var ytInitialData = (.*?);')

    def __init__(self, name: str = None, channel_id: str = None,
                 ingest: bool = False, api_client: YouTubeResource = None):

        self.name: str = name
        self.asset_ingest_enabled: bool = False
        self.channel_id: str | None = channel_id
        self.ingest_videos: bool = ingest
        self.api_client: YouTubeResource | None = api_client

        self.videos: dict[YouTubeVideo] = {}

    async def persist(self, member: Member, storage_driver: FileStorage,
                      already_ingested_videos: dict[str, dict] = {},
                      bento4_directory: str | None = None,
                      moderate_request_url: str | None = None,
                      moderate_jwt_header: str | None = None,
                      moderate_claim_url: str | None = None,
                      ingest_interval: int = 0) -> None:
        '''
        persist any video not yet in the public_assets collection to that
        collection, including downloading the video, packaging it, and
        saving it to the file store
        '''

        # The strategy here is simple: we try to store all videos. persist()
        # first checks whether the video is already in the data store and only
        # adds it if it is not. If the asset exists and has ingest status
        # 'external' and this channel is configured to download AV tracks
        # then the existing asset will be updated
        video: YouTubeVideo
        for video in self.videos.values():
            _LOGGER.debug(
                f'Persisting video {video.video_id} for channel {self.name}'
            )
            try:
                result = await video.persist(
                    member, storage_driver,
                    self.ingest_videos, already_ingested_videos,
                    bento4_directory,
                    moderate_request_url=moderate_request_url,
                    moderate_jwt_header=moderate_jwt_header,
                    moderate_claim_url=moderate_claim_url,
                )

                if result is None:
                    _LOGGER.debug(f'Failed to persist video {video.video_id}')

                if ingest_interval:
                    random_delay = \
                        random() * ingest_interval + ingest_interval / 2
                    await sleep(random_delay)
            except (ValueError, ByodaRuntimeError) as exc:
                _LOGGER.exception(
                    f'Could not persist video {video.video_id}: {exc}'
                )

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

        if filename:
            with open(filename, 'r') as file_desc:
                data = file_desc.read()
        else:
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/112.0.0.0 Safari/537.36'
                )
            }
            async with AsyncHttpClient(headers=headers) as client:
                url = YouTubeChannel.CHANNEL_URL_WITH_AT.format(
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

        soup = BeautifulSoup(data, 'html.parser')
        script = soup.find(
            'script', string=YouTubeChannel.CHANNEL_SCRAPE_REGEX
        )

        if not script:
            _LOGGER.warning('Did not find text in HTML scrape')
            return

        raw_data = YouTubeChannel.CHANNEL_SCRAPE_REGEX.search(
            script.text
        ).group(1)

        try:
            data = orjson.loads(raw_data)
        except orjson.JSONDecodeError as exc:
            _LOGGER.debug(
                f'Failed parsing JSON data for channel {self.channel_id}: '
                f'{exc}'
            )
            return

        # Also interesting is data['metadata']['microsoft']
        channel_thumbnails: list[dict[str, str]] = []
        try:
            keys: list[str] = [
                'metadata', 'channelMetadataRenderer', 'avatar', 'thumbnails'
            ]
            channel_thumbnails = YouTubeChannel._datagetter(data, keys)
        except (IndexError, KeyError) as exc:
            _LOGGER.debug(f'Failed to parse channel metadata: {exc}')

        creator_thumbnail: YouTubeThumbnail | None = None
        if (channel_thumbnails and isinstance(channel_thumbnails, list)
                and len(channel_thumbnails)
                and isinstance(channel_thumbnails[0], dict)
                and channel_thumbnails[0].get('url')):
            creator_thumbnail = YouTubeThumbnail(None, channel_thumbnails[0])

        self.find_videos(
            data, already_ingested_videos, self.ingest_videos,
            creator_thumbnail
        )

        _LOGGER.debug(
            f'Scraped {len(self.videos)} videos from '
            f'YouTube channel {self.name}'
        )

    @staticmethod
    def _datagetter(data: dict, keys: list[str]) -> object:
        if not keys:
            return data

        if keys[0] in data:
            if len(keys) == 1:
                return data[keys[0]]

            return YouTubeChannel._datagetter(data[keys[0]], keys[1:])

        return None

    def find_videos(self, data: dict | list | int | str | float,
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
                    self.find_videos(
                        item, already_ingested_videos, ingest_videos,
                        creator_thumbnail
                    )

        if not isinstance(data, dict):
            return

        video_id = data.get('videoId')

        if not video_id:
            for value in data.values():
                if type(value) in (dict, list):
                    self.find_videos(
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
                status = already_ingested_videos[video_id].get(
                        'ingest_status'
                    )
                if isinstance(status, str):
                    status = IngestStatus(status)
            except ValueError:
                status = IngestStatus.NONE

            if not ingest_videos and status == IngestStatus.EXTERNAL:
                _LOGGER.debug(
                    f'Skipping video {video_id} as it is already '
                    'ingested and we are not importing AV streams'
                )
                return
            elif status == IngestStatus.PUBLISHED:
                _LOGGER.debug(
                    f'Skipping video {video_id} that we already ingested '
                    'earlier in this run'
                )
                return

            _LOGGER.debug(
                f'Ingesting AV streams video {video_id} '
                f'with ingest status {status}'
            )
        else:
            if ingest_videos:
                status = IngestStatus.NONE

        video = YouTubeVideo.scrape(video_id, ingest_videos, creator_thumbnail)

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

    async def import_videos(self, already_ingested_videos: dict[str, str],
                            max_api_requests: int = 1000):
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
            1970, 1, 1, tzinfo=timezone.utc
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
