'''
Model a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os
import shutil
import subprocess

from enum import Enum
from uuid import UUID
from uuid import uuid4
from typing import Self
from random import randrange
from logging import getLogger
from byoda.util.logger import Logger
from datetime import datetime
from datetime import timezone
from dateutil import parser as dateutil_parser

import orjson

from anyio import sleep
from fastapi import FastAPI

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from byoda.datamodel.table import Table
from byoda.datamodel.table import QueryResult
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.network import Network
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.claim import Claim
from byoda.datamodel.claim import ClaimRequest

from byoda.datatypes import ClaimStatus
from byoda.datatypes import StorageType
from byoda.datatypes import IngestStatus
from byoda.datatypes import DataRequestType
from byoda.datatypes import IdType

from byoda.storage.filestorage import FileStorage

from byoda.secrets.secret import Secret

from byoda.requestauth.jwt import JWT

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.paths import Paths
from byoda.util.merkletree import ByoMerkleTree

from byoda.exceptions import ByodaRuntimeError

from byoda import config

from .youtube_thumbnail import YouTubeThumbnail
from .youtube_streams import TARGET_AUDIO_STREAMS, TARGET_VIDEO_STREAMS

_LOGGER: Logger = getLogger(__name__)

BENTO4_DIR: str = '/podserver/bento4'


class YouTubeFragment:
    '''
    Models a fragment of a YouTube video or audio track
    '''

    def __init__(self) -> None:
        self.url: str | None = None
        self.duration: float | None = None
        self.path: str | None = None

    def as_dict(self) -> dict[str, str | float]:
        '''
        Returns a dict representation of the fragment
        '''

        return {
            'url': self.url,
            'duration': self.duration,
            'path': self.path
        }

    @staticmethod
    def from_dict(data: dict[str, str | float]) -> Self:
        '''
        Factory for YouTubeFragment, parses data are provided
        by yt-dlp
        '''

        fragment = YouTubeFragment()
        fragment.url = data.get('url')
        fragment.path = data.get('path')
        fragment.duration = data.get('duration')
        return fragment


class YouTubeFormat:
    '''
    Models a track (audio, video, or storyboard of YouTube video
    '''

    def __init__(self) -> None:
        self.format_id: str | None = None
        self.format_note: str | None = None
        self.ext: str | None = None
        self.audio_ext: str | None = None
        self.video_ext: str | None = None
        self.protocol: str | None = None
        self.audio_codec: str | None = None
        self.video_codec: str | None = None
        self.container: str | None = None
        self.url: str | None = None
        self.width: int | None = None
        self.height: int | None = None
        self.fps: float | None = None
        self.quality: float | None = None
        self.dynamic_range: str | None = None
        self.has_drm: bool | None = None
        self.tbr: float | None = None
        self.abr: float | None = None
        self.asr: int | None = None
        self.audio_channels: int | None = None
        self.rows: int | None = None
        self.cols: int | None = None
        self.fragments: list[YouTubeFragment] = []
        self.resolution: str | None = None
        self.aspect_ratio: str | None = None
        self.format: str | None = None

    def __str__(self) -> str:
        return (
            f'YouTubeFormat('
            f'{self.format_id}, {self.format_note}, {self.ext}, '
            f'{self.protocol}, {self.audio_codec}, {self.video_codec}, '
            f'{self.container}, {self.width}, {self.height}, {self.fps}, '
            f'{self.resolution}, '
            f'{self.audio_ext}, {self.video_ext}'
            ')'
        )

    def as_dict(self) -> dict[str, any]:
        '''
        Returns a dict representation of the video
        '''

        data: dict[str, any] = {
            'format_id': self.format_id,
            'format_note': self.format_note,
            'ext': self.ext,
            'audio_ext': self.audio_ext,
            'video_ext': self.video_ext,
            'protocol': self.protocol,
            'audio_codec': self.audio_codec,
            'video_codec': self.video_codec,
            'container': self.container,
            'url': self.url,
            'width': self.width,
            'height': self.height,
            'fps': self.fps,
            'quality': self.quality,
            'dynamic_range': self.dynamic_range,
            'has_drm': self.has_drm,
            'tbr': self.tbr,
            'abr': self.abr,
            'asr': self.asr,
            'audio_channels': self.audio_channels,
            'rows': self.rows,
            'cols': self.cols,
            'fragments': [],
            'resolution': self.resolution,
            'aspect_ratio': self.aspect_ratio,
            'format': self.format,
        }

        for fragment in self.fragments:
            data['fragments'].append(fragment.as_dict())

        return data

    def from_dict(data: dict[str, any]) -> Self:
        '''
        Factory using data retrieved using the 'yt-dlp' tool
        '''

        format = YouTubeFormat()
        format.format_id = data['format_id']
        format.format_note = data.get('format_note')
        format.ext = data.get('ext')
        format.protocol = data.get('protocol')
        format.audio_codec = data.get('acodec')
        if format.audio_codec and format.audio_codec.lower() == 'none':
            format.audio_codec = None

        format.video_codec = data.get('vcodec')
        if format.video_codec and format.video_codec.lower() == 'none':
            format.video_codec = None

        format.container = data.get('container')
        format.audio_ext = data.get('audio_ext')
        format.video_ext = data.get('video_ext')
        format.url = data.get('url')
        format.width = data.get('width')
        format.height = data.get('height')
        format.fps = data.get('fps')
        format.tbr = data.get('tbr')
        format.asr = data.get('asr')
        format.abr = data.get('abr')
        format.rows = data.get('rows')
        format.cols = data.get('cols')
        format.audio_channels = data.get('audio_channels')
        format.dynamic_range = data.get('dynamic_range')

        format.resolution = data.get('resolution')
        format.aspect_ratio = data.get('aspect_ratio')
        format.audio_ext = data.get('audio_ext')
        format.video_ext = data.get('video_ext')
        format.format = data.get('format')

        for fragment_data in data.get('fragments', []):
            fragment: YouTubeFragment = YouTubeFragment.from_dict(
                fragment_data
            )
            format.fragments.append(fragment)

        return format


class YouTubeVideoChapter:
    def __init__(self, chapter_info: dict[str, float | str]) -> None:
        self.chapter_id: UUID = uuid4()
        self.start_time: float = chapter_info.get('start_time')
        self.end_time: float = chapter_info.get('end_time')
        self.title: str = chapter_info.get('title')

    def as_dict(self) -> dict[str, str, UUID, float]:
        '''
        Returns a dict representation of the chapter
        '''

        return {
            'chapter_id': self.chapter_id,
            'start': self.start_time,
            'end': self.end_time,
            'title': self.title
        }


class YouTubeVideo:
    VIDEO_URL: str = 'https://www.youtube.com/watch?v={video_id}'
    DATASTORE_CLASS_NAME: str = 'public_assets'
    DATASTORE_CLASS_NAME_THUMBNAILS: str = 'video_thumbnails'
    DATASTORE_CLASS_NAME_CHAPTERS: str = 'video_chapters'
    DATASTORE_CLASS_NAME_CLAIMS: str = 'claims'
    DATASTORE_FIELD_MAPPINGS: dict[str, str] = {
        'video_id': 'publisher_asset_id',
        'title': 'title',
        'description': 'contents',
        'published_time': 'published_timestamp',
        'url': 'asset_url',
        'channel_creator': 'creator',
        'creator_thumbnail': 'creator_thumbnail',
        'url': 'asset_url',
        'created_time': 'created_timestamp',
        'duration': 'duration',
        'asset_type': 'asset_type',
        'asset_id': 'asset_id',
        'locale': 'locale',
        'publisher': 'publisher',
        'ingest_status': 'ingest_status',
        'merkle_root_hash': 'asset_merkle_root_hash',
        'screen_orientation_horizontal': 'screen_orientation_horizontal',
        'categories': 'categories',
        'annotations': 'annotations',
        'view_count': 'publisher_views',
        'like_count': 'publisher_likes',
    }

    def __init__(self) -> None:
        self.video_id: str | None = None
        self.title: str | None = None
        self.kind: str | None = None
        self.long_title: str | None = None
        self.description: str | None = None
        self.channel_creator: str | None = None
        self.creator_thumbnail_asset: YouTubeThumbnail | None = None

        # URL for the thumbnail of the creator of the video
        self.creator_thumbnail: str | None = None
        self.channel_id: str | None = None
        self.published_time: datetime | None = None
        self.published_time_info: str | None = None
        self.view_count: int | None = None
        self.like_count: int | None = None
        self.url: str | None = None
        self.thumbnails: dict[YouTubeThumbnail] = {}
        self.duration: str | None = None
        self.is_live: bool | None = None
        self.was_live: bool | None = None
        self.availability: str | None = None
        self.embedable: bool | None = None
        self.age_limit: int | None = None
        self.screen_orientation_horizontal: bool = True

        # Duration of the video in seconds
        self.duration: int | None = None

        self.chapters: list[YouTubeVideoChapter] = []
        self.tags: list[str] = []

        # Data for the Byoda table with assets
        self.publisher = 'YouTube'
        self.asset_type: str = 'video'
        self.ingest_status: IngestStatus = IngestStatus.NONE

        # This is the default profile. If we ingest the asset from
        # YouTube then this will be overwritten with info about the
        # YouTube formats
        self.encoding_profiles: dict[str, YouTubeFormat] = {}
        self.asset_id: UUID = uuid4()
        self.locale: str | None = None
        self.annotations: list[str] = []
        self.categories: list[str] = []

        self.created_time: datetime = datetime.now(tz=timezone.utc)

        self.merkle_root_hash: str | None = None

        # If this has a value then it is not a video but a
        # playlist
        self.playlistId: str | None = None

    @staticmethod
    async def scrape(video_id: str, ingest_videos: bool, channel_name: str,
                     creator_thumbnail: YouTubeThumbnail | None) -> Self:
        '''
        Collects data about a video by scraping the webpage for the video

        :param video_id: YouTube video ID
        :param ingest_videos: whether the video will be ingested
        :param channel_name: Name of the channel that we are scraping
        :param creator_thumbnail: Thumbnail for the creator of the video
        page
        '''

        video = YouTubeVideo()

        video.video_id = video_id
        video.url = YouTubeVideo.VIDEO_URL.format(video_id=video_id)

        ydl_opts: dict[str, bool] = {
            'quiet': True,
            'logger': _LOGGER,
        }

        if config.debug:
            ydl_opts['verbose'] = True
            ydl_opts['quiet'] = False

        log_data: dict[str, str] = {
            'channel': channel_name,
            'video_id': video_id,
            'ingest_status': video.ingest_status.value
        }

        _LOGGER.debug(
            'Instantiating YouTubeDL client', extra=log_data
        )
        with YoutubeDL(ydl_opts) as ydl:
            try:
                _LOGGER.debug('Scraping YouTube video', extra=log_data)
                video_info: dict[str, any] = ydl.extract_info(
                    video.url, download=False
                )
                if video_info:
                    sleepy_time: int = randrange(2, 5)
                    _LOGGER.debug(
                        'Collected info for video, sleeping',
                        extra=log_data | {'seconds': sleepy_time}
                    )
                    await sleep(sleepy_time)
                else:
                    sleepy_time: int = randrange(10, 30)
                    _LOGGER.debug(
                        'Video scrape failed, sleeping',
                        extra=log_data | {'seconds': sleepy_time}
                    )
                    await sleep(sleepy_time)
                    return
            except DownloadError as exc:
                sleepy_time: int = randrange(2, 5)
                video._transition_state(IngestStatus.UNAVAILABLE)
                log_data['ingest_status'] = video.ingest_status.value
                _LOGGER.info(
                    f'Failed to extract info for video, sleeping: {exc}',
                    extra=log_data | {'seconds': sleepy_time}
                )
                video._transition_state(IngestStatus.UNAVAILABLE)
                await sleep(sleepy_time)
                return video

            except Exception as exc:
                sleepy_time: int = randrange(10, 30)
                _LOGGER.info(
                    f'Failed to extract info for video: {exc}',
                    extra=log_data | {'seconds': sleepy_time}
                )
                await sleep(sleepy_time)
                return None

            video.channel_creator = video_info.get('channel')
            if channel_name and channel_name != video.channel_creator:
                video._transition_state(IngestStatus.UNAVAILABLE)
                log_data['ingest_status'] = video.ingest_status.value
                _LOGGER.debug(
                    f'Skipping video from channel {video.channel_creator} '
                    f'different from {channel_name}', extra=log_data
                )
                return video

            if video_info.get('is_live'):
                _LOGGER.debug('Skipping live video', extra=log_data)
                return None

            video.embedable = video_info.get('playable_in_embed', True)
            if not (video.embedable or ingest_videos):
                _LOGGER.debug('Skipping non-embedable video', extra=log_data)
                return None

            video.description = video_info.get('description')
            video.title = video_info.get('title')
            video.view_count = video_info.get('view_count')
            video.like_count = video_info.get('like_count')
            video.duration = video_info.get('duration')
            video.long_title = video_info.get('fulltitle')
            video.is_live = video_info.get('is_live')
            video.was_live = video_info.get('was_live')
            video.availability = video_info.get('availability')
            video.duration = video_info.get('duration')
            video.annotations = video_info.get('tags')
            video.categories = video_info.get('categories')
            video.creator_thumbnail_asset = creator_thumbnail

            video.age_limit = video_info.get('age_limit', 0)

            try:
                if int(video.age_limit) >= 18 and not ingest_videos:
                    _LOGGER.debug(
                        'Video is for 18+ videos and can not be embedded',
                        extra=log_data
                    )
                    return
            except ValueError:
                pass

            # For fully ingested assets, the _ingest_video method
            # updates the url of the thumbnail
            video.creator_thumbnail = None
            if creator_thumbnail:
                video.creator_thumbnail = creator_thumbnail.url

            video.published_time = dateutil_parser.parse(
                video_info['upload_date']
            )
            video.channel_id = video_info.get('channel_id')

            for thumbnail in video_info.get('thumbnails') or []:
                thumbnail = YouTubeThumbnail(None, thumbnail)
                if thumbnail.size and thumbnail.url:
                    # We only want to store thumbnails for which
                    # we know the size and have a URL
                    video.thumbnails[thumbnail.size] = thumbnail
                else:
                    _LOGGER.debug(
                        f'Not importing thumbnail without size '
                        f'({thumbnail.size}) or URL ({thumbnail.url})'
                    )

            for chapter_data in video_info.get('chapters') or []:
                chapter = YouTubeVideoChapter(chapter_data)
                video.chapters.append(chapter)

            max_height: int = 0
            max_width: int = 0
            for format_data in video_info.get('formats') or []:
                format: YouTubeFormat = YouTubeFormat.from_dict(format_data)
                if format.height and format.height > max_height:
                    max_height = format.height
                if format.width and format.width > max_width:
                    max_width = format.width
                video.encoding_profiles[format.format_id] = format

            if max_height > max_width:
                video.screen_orientation_horizontal = False

            _LOGGER.debug(
                'Parsed all available data for video', extra=log_data
            )
        return video

    @staticmethod
    def get_video_id_from_api(data) -> str:
        '''
        Extract the video ID from the data returned by the YouTube Data API

        :param data: data as returned by the YouTube Data API
        :returns: the video ID
        '''

        if 'id' not in data:
            raise ValueError('Invalid data from YouTube API: no id')

        video_id: str = data['id']['videoId']

        return video_id

    def get_publish_datetime_from_api(data) -> datetime:
        '''
        Extract the publication date/time from the data returned by the
        YouTube Data API

        :param data: data as returned by the YouTube Data API
        :returns: the publication date/time
        '''

        snippet: dict = data.get('snippet')
        if not snippet:
            raise ValueError('Invalid data from YouTube API: no snippet')

        if 'publishedAt' not in snippet:
            raise ValueError('Invalid data from YouTube API: no publishedAt')

        published_at: datetime = dateutil_parser.parse(snippet['publishedAt'])

        return published_at

    def _transition_state(self, ingest_status: IngestStatus | str) -> None:
        '''
        Transition the ingest state of the video

        :param ingest_status: the new ingest state
        '''

        if isinstance(ingest_status, str):
            ingest_status = IngestStatus(ingest_status)

        log_data: dict[str, str] = {
            'channel': self.channel_creator,
            'video_id': self.video_id,
            'ingest_status': self.ingest_status.value
        }

        _LOGGER.debug(
            f'Video transitioned to {ingest_status}', extra=log_data
        )
        self.ingest_status = ingest_status

    def as_claim_data(self) -> dict:
        '''
        Returns a dict with the data to be signed for moderation by the
        app server

        :param member: the member
        :returns: the data to be signed by the moderation server
        '''

        claim_data: dict[str, any] = {
            'asset_id': self.asset_id,
            'asset_type': self.asset_type,
            'asset_url': self.url,
            'asset_merkle_root_hash': self.merkle_root_hash,
            'video_thumbnails': [
                thumbnail.url for thumbnail in self.thumbnails.values()
                ],
            'creator': self.channel_creator,
            'publisher': self.publisher,
            'publisher_asset_id': self.video_id,
            'title': self.title,
            'contents': self.description,
            'annotations': self.annotations
        }

        return claim_data

    async def get_claim_request(self, moderate_request_url: str,
                                jwt_header: str,
                                claims: list[str]) -> ClaimRequest:
        '''
        Submits a claim request to the moderation server

        :param moderate_request_url: URL of the moderation API of the
        moderation app
        :param jwt header: JWT header to authenticate the request
        :returns: the claim
        '''

        claim_request: Claim = await ClaimRequest.from_api(
            moderate_request_url, jwt_header, claims, self.as_claim_data()
        )

        return claim_request

    async def persist(
        self, member: Member, storage_driver: FileStorage, ingest_asset: bool,
        video_table: Table, bento4_directory: str = None,
        moderate_request_url: str | None = None,
        moderate_jwt_header: str = None,
        moderate_claim_url: str | None = None,
        custom_domain: str | None = None,
    ) -> bool | None:
        '''
        Adds or updates a video in the datastore.

        :param member: The member
        :param data_store: The data store to store the videos in
        :param storage_driver: The storage driver to store the video with
        :param ingest_asset: should the A/V tracks of the asset be downloaded
        :param already_ingested_videos: dict with key the YouTube Video ID
        and as value a dict with 'ingest_status' and 'created_timestamp'
        :param bento4_directory: directory where to find the BenTo4 MP4
        packaging tool
        :param claim: a claim for the video signed by a moderate API
        :returns: True if the video was added, False if it already existed, or
        None if an error was encountered
        '''

        if not storage_driver:
            raise ValueError(
                'storage_driver must be provided if ingest_asset is True'
            )

        log_data: dict[str, str] = {
            'video_id': self.video_id, 'channel': self.channel_creator,
            'ingest_status': self.ingest_status.value
        }

        update: bool = False
        claim_request: ClaimRequest | None = None
        unavailable: IngestStatus = IngestStatus.UNAVAILABLE
        if self.ingest_status != unavailable:
            # We import thumbnails regardless of ingress setting so that
            # the browser doesn't have to download these from YouTube, which
            # may improve privacy
            await self._ingest_thumbnails(
                storage_driver, member, custom_domain=custom_domain
            )

        log_data['ingest_status'] = self.ingest_status.value
        if self.ingest_status != unavailable:
            if not ingest_asset:
                self._transition_state(IngestStatus.EXTERNAL)
                log_data['ingest_status'] = self.ingest_status.value
                _LOGGER.debug(
                    'Setting ingest status to EXTERNAL', extra=log_data
                )
            else:
                try:
                    _LOGGER.debug(
                        'Ingesting AV tracks for video', extra=log_data
                    )
                    update = await self._ingest_assets(
                        member, storage_driver, video_table,
                        bento4_directory, custom_domain=custom_domain
                    )
                    log_data['ingest_status'] = self.ingest_status.value

                    if (self.ingest_status != IngestStatus.UNAVAILABLE
                            and (moderate_request_url and moderate_jwt_header
                                 and moderate_claim_url)):
                        _LOGGER.debug(
                            f'Getting moderation claim for video '
                            f'signed by {moderate_request_url}',
                            extra=log_data
                        )
                        claims: list[str] = ['youtube-moderated:1']
                        claim_request = await self.get_claim_request(
                            moderate_request_url, moderate_jwt_header,
                            claims
                        )
                    else:
                        _LOGGER.debug(
                            'Not trying to get a claim signed for video',
                            extra=log_data
                        )

                    # We now set state to PUBLISHED because we need that value
                    # to be written to the database
                    if self.ingest_status != unavailable:
                        self._transition_state(IngestStatus.PUBLISHED)
                        log_data['ingest_status'] = self.ingest_status.value

                except (ValueError, ByodaRuntimeError) as exc:
                    if config.test_case:
                        _LOGGER.debug(
                            'Test case, not bothering about moderation failure'
                        )
                    else:
                        _LOGGER.exception(
                            f'Ingesting asset for YouTube video failed: {exc}',
                            extra=log_data
                        )
                        raise

        asset: dict[str, any] = {}
        for field, mapping in YouTubeVideo.DATASTORE_FIELD_MAPPINGS.items():
            value: any = getattr(self, field)
            if value:
                if isinstance(value, Enum):
                    asset[mapping] = value.value
                else:
                    asset[mapping] = value

        if claim_request:
            if claim_request.signature and not config.test_case:
                claim_data: dict[str, any] = await self.download_claim(
                    moderate_claim_url
                )

                # Moderation server returns the data that is covered by
                # its signature but we don't need that info as we already
                # have it as part of the asset
                claim_data.pop('claim_data')
                asset[YouTubeVideo.DATASTORE_CLASS_NAME_CLAIMS] = [claim_data]
            else:
                storage_driver.save(
                    f'claim_requests/pending/{self.asset_id}',
                    orjson.dumps(claim_request, orjson.OPT_INDENT_2)
                )

        asset[YouTubeVideo.DATASTORE_CLASS_NAME_THUMBNAILS] = [
            thumbnail.as_dict() for thumbnail in self.thumbnails.values() or []
        ]

        asset[YouTubeVideo.DATASTORE_CLASS_NAME_CHAPTERS] = [
            chapter.as_dict() for chapter in self.chapters or []
        ]

        network: Network = member.network
        schema: Schema = member.schema
        data_class: SchemaDataArray = \
            schema.data_classes[YouTubeVideo.DATASTORE_CLASS_NAME]

        # For test cases, we need to set up authentication for use with
        # FastAPI APP instead of making an actual HTTP call against a
        # pod server
        app: FastAPI | None = None
        auth_header: dict[str, str] = None
        auth_secret: Secret | None = member.tls_secret
        if config.test_case:
            app = config.app
            auth_secret = None
            jwt: JWT = JWT.create(
                member.member_id, IdType.MEMBER, member.data_secret,
                member.network.name, member.service_id,
                IdType.MEMBER, member.member_id
            )
            auth_header = jwt.as_header()

        # Using a Data REST API call to ourselves will make sure that
        # the app server sends out notifications to subscribers. Our
        # worker process can not write to the named pipes of Nng.
        query_id: UUID = uuid4()
        resp: HttpResponse = await DataApiClient.call(
            member.service_id, data_class.name, DataRequestType.APPEND,
            secret=auth_secret, network=network.name, headers=auth_header,
            member_id=member.member_id, data={'data': asset},
            query_id=query_id, app=app
        )

        if resp.status_code != 200:
            _LOGGER.warning(
                f'Failed to ingest video with query_id {query_id}: '
                f'{resp.status_code}', extra=log_data
            )
            return None

        _LOGGER.info(
            'Added YouTube video', extra=log_data
        )

        return not update

    def download(self, video_formats: set[str], audio_formats: set[str],
                 work_dir: str = None) -> str | None:
        '''
        Downloads the video and audio streams of the video. Stores the
        different files in work_directory. Will create 'work_dir' if it
        does not exist.

        :param video_formats: the YouTube video format IDs to download
        :param audio_formats: the YouTube audio format IDs to download
        :returns: whether the download was successful
        :raises: OSError if work_dir exists and is not empty
        '''

        if not work_dir:
            work_dir = f'/tmp/{self.video_id}'

        log_data: dict[str, str] = {
            'video_id': self.video_id, 'channel': self.channel_creator,
            'ingest_status': self.ingest_status.value
        }

        self._transition_state(IngestStatus.DOWNLOADING)
        log_data['ingest_status'] = self.ingest_status.value

        if config.test_case and os.path.exists(work_dir):
            _LOGGER.debug(
                'Skipping download of video in test case', extra=log_data
            )
            return work_dir

        os.makedirs(work_dir, exist_ok=True)

        ydl_opts: dict[str, any] = {
            'quiet': True,
            'logger': _LOGGER,
            'noprogress': True,
            'no_color': True,
            'format': ','.join(video_formats | audio_formats),
            'outtmpl': {'default': 'asset%(id)s.%(format_id)s.%(ext)s'},
            'paths': {'home': work_dir, 'temp': work_dir},
            'fixup': 'never',
        }

        if config.debug:
            ydl_opts['verbose'] = True
            ydl_opts['quiet'] = False

        _LOGGER.debug(
            'Instantiating YouTubeDL client', extra=log_data
        )
        with YoutubeDL(ydl_opts) as ydl:
            try:
                _LOGGER.debug(
                    f'Downloading YouTube video to {work_dir} started',
                    extra=log_data
                )
                ydl.download([self.url])
                _LOGGER.debug(
                    f'Download of YouTube video to {work_dir} completed',
                    extra=log_data
                )
            except (DownloadError, Exception) as exc:
                _LOGGER.info(
                    f'Failed to download YouTube video: {exc}',
                    extra=log_data
                )
                return None

        return work_dir

    async def download_claim(self, moderate_claim_url: str) -> dict[str, any]:
        '''
        Downloads a signed claim
        '''

        resp: HttpResponse = await ApiClient.call(
            moderate_claim_url.format(
                state=ClaimStatus.ACCEPTED.value, asset_id=self.asset_id
            )
        )
        if resp.status_code != 200:
            raise RuntimeError(
                'Failed to get the approved claim from moderation API '
                f'{moderate_claim_url}: {resp.status_code}'
            )

        claim_data: dict[str, any] = resp.json()

        return claim_data

    async def _ingest_assets(
        self, member: Member, storage_driver: FileStorage, video_table: Table,
        bento4_directory: str, custom_domain: str | None = None
    ) -> bool | None:
        '''
        Downloads to audio and video files of the asset and stores them
        on object storage

        :param storage_driver: The storage driver to store the video with
        :param ingest_asset: should the A/V tracks of the asset be downloaded
        :param video_table: Table for persisting videos
        :param bento4_directory: directory where to find the BenTo4 MP4
        packaging tool
        :returns: True if the video was updated, False if it was created,
        None if an error was encountered
        :raises: ValueError if the ingest status of the video is invalid
        '''

        log_data: dict[str, str] = {
            'video_id': self.video_id, 'channel': self.channel_creator,
            'ingest_status': self.ingest_status.value
        }

        _LOGGER.debug('Ingesting AV for video', extra=log_data)

        data_filter: DataFilterSet = DataFilterSet(
            {'publisher_asset_id': {'eq': self.video_id}}
        )
        video_data: list[QueryResult] | None = await video_table.query(
            data_filter
        )
        update: bool = False
        if video_data:
            try:
                current_status: str | IngestStatus = \
                    video_data.get('ingest_status')

                if not isinstance(current_status, IngestStatus):
                    current_status = IngestStatus(current_status)
            except ValueError:
                _LOGGER.warning(
                    f'Video has an invalid ingest status '
                    f'{current_status}, skipping ingest', extra=log_data
                )
                raise

            if current_status == IngestStatus.PUBLISHED:
                return False

            if current_status == IngestStatus.EXTERNAL:
                update = True

        tmp_dir: str = self._get_tempdir(storage_driver)

        try:
            download_dir: str | None = self.download(
                TARGET_VIDEO_STREAMS, TARGET_AUDIO_STREAMS, work_dir=tmp_dir
            )
            if not download_dir:
                return None

            pkg_dir: str = self.package_streams(
                tmp_dir, bento4_dir=bento4_directory
            )

            await self.upload(pkg_dir, storage_driver)

            tree: ByoMerkleTree = ByoMerkleTree.calculate(directory=pkg_dir)
            self.merkle_root_hash = tree.as_string()

            tree_filename: str = tree.save(pkg_dir)
            await storage_driver.copy(
                f'{pkg_dir}/{tree_filename}',
                f'{self.asset_id}/{tree_filename}',
                storage_type=StorageType.RESTRICTED, exist_ok=True
            )
        except Exception as exc:
            _LOGGER.exception(
                f'Ingesting asset for YouTube video failed: {exc}',
                extra=log_data
            )
            self._transition_state(IngestStatus.UNAVAILABLE)
            return None
        finally:
            self._delete_tempdir(storage_driver)

        cdn_origin_site_id: str | None = os.environ.get('CDN_ORIGIN_SITE_ID')

        if cdn_origin_site_id:
            _LOGGER.debug(
                'Using CDN Origin Site ID for thumbnail: '
                f'{cdn_origin_site_id}', extra=log_data
            )
            self.url: str = Paths.RESTRICTED_ASSET_CDN_URL.format(
                cdn_origin_site_id=cdn_origin_site_id,
                member_id=member.member_id, service_id=member.service_id,
                asset_id=self.asset_id, filename='video.mpd'
            )
        else:
            _LOGGER.debug(
                'Did not find a CDN app for the server', extra=log_data
            )
            if not custom_domain:
                raise ValueError(
                    'Custom domain must be provided if not using a CDN'
                )
            self.url: str = Paths.RESTRICTED_ASSET_POD_URL.format(
                custom_domain=custom_domain, asset_id=self.asset_id,
                filename='video.mpd'
            )

        return update

    async def _ingest_thumbnails(
        self, storage_driver: FileStorage, member: Member,
        custom_domain: str | None = None
    ) -> int | None:
        '''
        Ingests the thumbnails of the video and its creator

        :param storage_driver: the storage driver to upload the video with
        :param member: the membership for the service
        '''

        log_data: dict[str, str] = {
            'video_id': self.video_id,
            'channel': self.channel_creator,
            'asset_id': self.asset_id,
            'ingest_status': self.ingest_status.value
        }

        _LOGGER.debug(
            'Starting ingest of thumbnails', extra=log_data
        )

        thumbnails_counter = 0
        tmp_dir: str = self._create_tempdir(storage_driver)
        for thumbnail in self.thumbnails.values():
            _LOGGER.debug(
                f'Starting ingest of thumbnail {thumbnail.url}',
                extra=log_data
            )
            try:
                await thumbnail.ingest(
                    self.asset_id, storage_driver, member, tmp_dir,
                    custom_domain=custom_domain
                )
                thumbnails_counter += 1
            except ByodaRuntimeError:
                self._transition_state(IngestStatus.UNAVAILABLE)
                self._delete_tempdir(storage_driver)
                return None

        if self.creator_thumbnail_asset:
            _LOGGER.debug(
                'Starting ingest of creator thumbnail from '
                f'{self.creator_thumbnail_asset.url}',
                extra=log_data
            )
            try:
                self.creator_thumbnail = \
                    await self.creator_thumbnail_asset.ingest(
                        self.asset_id, storage_driver, member, tmp_dir,
                        custom_domain=custom_domain
                    )
                thumbnails_counter += 1
            except ByodaRuntimeError:
                self._transition_state(IngestStatus.UNAVAILABLE)
                self._delete_tempdir(storage_driver)
                return None

        self._delete_tempdir(storage_driver)

        _LOGGER.debug(
            f'Ingested {thumbnails_counter} thumbnails',
            extra=log_data
        )

        return thumbnails_counter

    async def upload(self, pkg_dir: str, storage_driver: FileStorage) -> None:
        '''
        Uploads the packaged video to object storage

        :param pkg_dir: directory where the packaged video is located
        :param storage_driver: the storage driver to upload the video with
        :param asset_id: the ID of the asset
        '''

        log_data: dict[str, str] = {
            'video_id': self.video_id,
            'channel': self.channel_creator,
            'asset_id': self.asset_id,
            'ingest_status': self.ingest_status.value
        }

        self._transition_state(IngestStatus.UPLOADING)

        for filename in os.listdir(pkg_dir):
            source: str = f'{pkg_dir}/{filename}'
            dest: str = f'{self.asset_id}/{filename}'
            _LOGGER.debug(
                f'Copying {source} to {dest} on RESTRICTED storage',
                extra=log_data
            )

            await storage_driver.copy(
                source, dest, storage_type=StorageType.RESTRICTED,
                exist_ok=True
            )

    def _get_tempdir(self, storage_driver: FileStorage) -> str:
        tmp_dir: str = storage_driver.local_path + 'tmp/' + self.video_id

        return tmp_dir

    def _create_tempdir(self, storage_driver: FileStorage) -> str:
        tmp_dir: str = self._get_tempdir(storage_driver)
        os.makedirs(tmp_dir, exist_ok=True)

        return tmp_dir

    def _delete_tempdir(self, storage_driver: FileStorage) -> None:
        tmp_dir: str = self._get_tempdir(storage_driver)
        shutil.rmtree(tmp_dir)

    def filter_encoding_profiles(
            self, wanted_encoding_profiles: dict[str, dict[str, str | bool]]
            ) -> set[int]:
        '''
        Filters the encoding profiles to only include the wanted formats

        :param wanted_encoding_profiles: the wanted video or audio encoding
        profiles
        '''

        log_data: dict[str, str] = {
            'video_id': self.video_id,
            'channel': self.channel_creator,
            'asset_id': self.asset_id,
            'ingest_status': self.ingest_status.value
        }

        included_profiles: set[int] = set()

        for id, data in wanted_encoding_profiles.items():
            if not data['wanted']:
                continue

            if id in included_profiles:
                continue

            if id in self.encoding_profiles:
                included_profiles.add(id)
                continue

            replacement: int = data['replacement']
            while replacement is not None:
                if replacement in wanted_encoding_profiles:
                    included_profiles.add(replacement)
                    break
                replacement = wanted_encoding_profiles[replacement].get(
                    'replacement'
                )

        _LOGGER.debug(
            f'Tracks selected to ingest {", ".join(included_profiles)}',
            extra=log_data
        )

        return included_profiles

    def package_streams(self, work_dir: str, bento4_dir: str = BENTO4_DIR
                        ) -> str:
        '''
        Creates MPEG-DASH and HLS manifests for the video and audio streams
        in work_dir

        :returns: the location of the packaged files
        '''

        log_data: dict[str, str] = {
            'video_id': self.video_id,
            'channel': self.channel_creator,
            'asset_id': self.asset_id,
            'ingest_status': self.ingest_status.value
        }

        if not bento4_dir:
            bento4_dir = BENTO4_DIR

        file_names: list[str] = [
            f'{work_dir}/{file_name}' for file_name in os.listdir(work_dir)
            if not file_name.endswith('.json')
        ]

        _LOGGER.debug(
            'Packaging MPEG-DASH and HLS manifests for '
            f'files: {", ".join(file_names)}', extra=log_data
        )

        self._transition_state(IngestStatus.PACKAGING)

        # https://www.bento4.com/documentation/mp4dash/
        result: subprocess.CompletedProcess[str] = subprocess.run(
            [
                f'{bento4_dir}/bin/mp4dash',
                '--no-split', '--use-segment-list', '--use-segment-timeline',
                '--mpd-name', 'video.mpd',
                '--hls', '--hls-master-playlist-name', 'video.m3u8',
                '-o', f'{work_dir}/packaged',
                *file_names
            ],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            _LOGGER.debug('Packaging successful', extra=log_data)
        else:
            raise RuntimeError(
                f'Packaging failed for asset {self.video_id}: {result.stderr}'
            )

        return f'{work_dir}/packaged'
