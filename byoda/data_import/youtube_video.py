'''
Model a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import os
import re
import shutil
import logging
import subprocess

from copy import copy
from enum import Enum
from uuid import UUID
from uuid import uuid4
from typing import Self
from shutil import copytree
from random import randrange
from logging import Logger
from logging import getLogger
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
from byoda.datamodel.monetization import Monetizations
from byoda.datamodel.monetization import BurstMonetization

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
from byoda.util.test_tooling import convert_number_string

from byoda.servers.pod_server import PodServer

from byoda.exceptions import ByodaException, ByodaValueError
from byoda.exceptions import ByodaRuntimeError

from byoda import config

from .youtube_format import YouTubeFormat
from .youtube_thumbnail import YouTubeThumbnail
from .youtube_streams import EncodingCategory
from .youtube_streams import TARGET_AUDIO_STREAMS
from .youtube_streams import TARGET_VIDEO_STREAMS
from .youtube_client import AsyncYouTubeClient

_LOGGER: Logger = getLogger(__name__)

BENTO4_DIR: str = '/podserver/bento4'


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


class YouTubeCaption:
    def __init__(self, language_code: str, is_auto_generated: bool,
                 caption_info: dict[str, str]) -> None:
        '''
        Describes a caption / subtitle track for a YouTube video

        :param language_code: BCP-47 language code for the caption
        :param is_auto_generated: whether the caption track is auto-generated
        :param caption_info: information about the caption track
        :returns: (none)
        :raises: (none)
        '''

        self.caption_id: UUID = uuid4()
        self.language_code: str = language_code
        self.is_auto_generated: bool = is_auto_generated
        self.url: str = caption_info.get('url')
        self.extension: str = caption_info.get('ext')
        self.protocol: str = caption_info.get('protocol')

    def as_dict(self) -> dict[str, str]:
        '''
        Returns a dict representation of the caption
        '''

        return {
            'caption_id': self.caption_id,
            'language_code': self.language_code,
            'is_auto_generated': self.is_auto_generated,
            'url': self.url,
            'extension': self.extension,
            'protocol': self.protocol
        }


class YouTubeVideo:
    VIDEO_URL: str = 'https://www.youtube.com/watch?v={video_id}'
    DATASTORE_CLASS_NAME: str = 'public_assets'
    DATASTORE_CLASS_NAME_THUMBNAILS: str = 'video_thumbnails'
    DATASTORE_CLASS_NAME_CHAPTERS: str = 'video_chapters'
    DATASTORE_CLASS_NAME_CLAIMS: str = 'claims'
    DATASTORE_FIELD_MAPPINGS: dict[str, str] = {
        'created_timestamp': 'created_timestamp',
        'asset_id': 'asset_id',
        'asset_type': 'asset_type',
        'url': 'asset_url',
        'merkle_root_hash': 'asset_merkle_root_hash',
        'locale': 'locale',
        'default_audio_language': 'default_audio_language',
        'channel': 'publisher_channel',
        'channel_thumbnail_url': 'channel_thumbnail',
        'uploaded_timestamp': 'uploaded_timestamp',
        'published_timestamp': 'published_timestamp',
        'license': 'license',
        'publisher': 'publisher',
        'video_id': 'publisher_asset_id',
        'view_count': 'publisher_views',
        'like_count': 'publisher_likes',
        'dislike_count': 'publisher_dislikes',
        'comment_count': 'publisher_comment_count',
        'title': 'title',
        'description': 'contents',
        'is_live': 'is_live',
        'was_live': 'was_live',
        'keywords': 'keywords',
        'tags': 'tags',
        'annotations': 'annotations',
        'categories': 'categories',
        'duration': 'duration',
        'channel_id': 'publisher_channel_id',
        'ingest_status': 'ingest_status',
        'screen_orientation_horizontal': 'screen_orientation_horizontal',
        'is_family_safe': 'is_family_safe',
        'age_limit': 'age_limit',
    }

    def __init__(self,
                 video_id: str | None = None,
                 user_agent: str | None = None,
                 consent_cookies: dict[str, str] = {},
                 use_consent_cookies: bool = True,
                 browse_client: YoutubeDL | None = None,
                 download_client: YoutubeDL | None = None,
                 storage_driver: FileStorage | None = None) -> None:

        # Consent cookies needed for YouTubeClient and yt-dlp
        self.consent_cookies: dict[str, str] = consent_cookies
        self.browse_client: YoutubeDL | None = browse_client
        self.download_client: YoutubeDL | None = download_client

        self.asset_id: UUID = uuid4()

        self.video_id: str | None = video_id
        self.title: str | None = None
        self.kind: str | None = None
        self.long_title: str | None = None
        self.description: str | None = None

        # Info about the channel
        self.channel_id: str | None = None
        self.channel: str | None = None
        self.channel_thumbnail: str | None = None
        self.channel_thumbnail_asset: YouTubeThumbnail | None = None
        self.channel_thumbnail_url: str | None = None

        self.created_timestamp: datetime = datetime.now(tz=timezone.utc)
        self.uploaded_timestamp: datetime | None = None
        self.published_timestamp: datetime | None = None
        self.availability: str | None = None

        self.view_count: int | None = None
        self.like_count: int | None = None
        self.dislike_count: int | None = None
        self.comment_count: int | None = None

        self.url: str | None = None
        self.short_url: str | None = None
        self.embed_url: str | None = None
        self.thumbnails: dict[YouTubeThumbnail] = {}

        self.is_live: bool = False
        self.was_live: bool = False
        self.is_short: bool = False
        self.embedable: bool | None = None

        self.age_limit: int = 0
        self.age_restricted: bool = False
        self.is_family_safe: bool | None = None
        self.screen_orientation_horizontal: bool = True

        # Duration of the video in seconds
        self.duration: int | None = None

        self.chapters: list[YouTubeVideoChapter] = []
        self.captions: list[YouTubeCaption] = []
        self.heatmaps: list[dict[str, float]] = []
        self.monetizations: Monetizations | None = None

        # Data for the Byoda table with assets
        self.publisher = 'YouTube'
        self.asset_type: str = 'video'
        self.license: str | None = None
        self.ingest_status: IngestStatus = IngestStatus.NONE

        # This is the default profile. If we ingest the asset from
        # YouTube then this will be overwritten with info about the
        # YouTube formats
        self.encoding_profiles: dict[str, YouTubeFormat] = {}

        self.locale: str | None = None
        self.default_audio_language: str | None = 'en'

        self.tags: set[str] = set()
        self.annotations: set[str] = set()
        self.categories: set[str] = set()
        self.keywords: set[str] = set()
        self.privacy_status: str = 'public'

        self._work_dir: str | None = None

        self.merkle_root_hash: str | None = None

        # If this has a value then it is not a video but a
        # playlist
        self.playlistId: str | None = None

        self.client: AsyncYouTubeClient = AsyncYouTubeClient(
            user_agent=user_agent, consent_cookies=consent_cookies,
            use_consent_cookies=use_consent_cookies
        )
        self.ydl: YoutubeDL | None = None

        if storage_driver:
            self.storage_driver: FileStorage = storage_driver
            self._work_dir: str = self._get_tempdir(storage_driver)

    @staticmethod
    async def scrape(
        video_id: str, ingest_videos: bool, channel_name: str | None,
        channel_thumbnail: YouTubeThumbnail | None,
        consent_cookies: dict[str, str] = {},
        browse_client: YoutubeDL | None = None,
        download_client: YoutubeDL | None = None,
        storage_driver: FileStorage | None = None
    ) -> Self | None:
        '''
        Collects data about a video by scraping the webpage for the video

        :param video_id: YouTube video ID
        :param ingest_videos: whether the video will be ingested
        :param channel_name: Name of the channel that we are scraping
        :param channel_thumbnail: Thumbnail for the creator of the video
        page
        '''

        log_extra: dict[str, str | int] = {'video_id': video_id}

        self: YouTubeVideo = YouTubeVideo(
            video_id=video_id,
            consent_cookies=consent_cookies,
            browse_client=browse_client,
            download_client=download_client,
            storage_driver=storage_driver
        )

        canonical_url: str = self.VIDEO_URL.format(video_id=video_id)
        html_content: str | None = await self.client.get(canonical_url)

        # Extract initial data
        initial_data: dict[str, any] = self._extract_initial_data(html_content)
        player_response: dict[str, any] = self._extract_player_response(
            html_content
        )

        self._parse_video_html(initial_data, player_response)

        await self._scrape_video(
            ingest_videos=ingest_videos, channel_name=channel_name,
            channel_thumbnail=channel_thumbnail
        )

        self.is_short = self._is_short(initial_data)

        return self

    def _extract_initial_data(self, html_content: str) -> dict:
        '''
        Extract ytInitialData from the HTML page

        :param html_content: HTML content of the video page
        :returns: dict with player response data
        :raises: ByodaValueError if data could not be extracted
        '''

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
                    json_str: str = match.group(1).replace("\\'", "'")
                    return orjson.loads(json_str)
                except orjson.JSONDecodeError:
                    continue

        raise ByodaValueError(
            'Could not extract initial data from video page',
            loglevel=logging.INFO, extra={'video_id': self.video_id}
        )

    def _extract_player_response(self, html_content: str) -> dict:
        '''
        Extract ytInitialPlayerResponse from the HTML page

        :param html_content: HTML content of the video page
        :returns: dict with player response data
        :raises: ByodaValueError if data could not be extracted
        '''
        patterns: list[str] = [
            r'ytInitialPlayerResponse\s*=\s*({.*?});',
            r'var ytInitialPlayerResponse = ({.*?});',
        ]

        for pattern in patterns:
            match: re.Match[str] | None = re.search(
                pattern, html_content, re.DOTALL
            )
            if match:
                try:
                    json_str: str = match.group(1)
                    json_str = json_str.replace("\\'", "'")
                    return orjson.loads(json_str)
                except orjson.JSONDecodeError:
                    continue

        raise ByodaValueError(
            'Could not extract player response data from video page',
            loglevel=logging.INFO, extra={'video_id': self.video_id}
        )

    def _parse_video_html(self, initial_data: dict,
                          player_response: dict) -> None:
        '''
        Parse the metadata scraped from a YouTube video page

        :param initial_data:
        :param player_response:
        :returns: (none)
        :raises: (none)
        '''

        # Basic info from player response
        video_details: dict[str, any] = player_response.get('videoDetails', {})
        microformat: dict[str, any] = player_response.get(
            'microformat', {}
        ).get(
            'playerMicroformatRenderer'
        )
        if not video_details or not microformat:
            _LOGGER.info(
                'Missing microformat data for video',
                extra={'video_id': self.video_id}
            )
            raise ValueError('Missing microformat data for video')

        # Video ID and URLs
        self.url = f'https://www.youtube.com/watch?v={self.video_id}'
        self.short_url = f'https://youtu.be/{self.video_id}'
        self.embed_url = f'https://www.youtube.com/embed/{self.video_id}'

        self.title = video_details.get('title')
        self.description = video_details.get('shortDescription')

        try:
            self.duration = int(
                microformat.get(
                    'lengthSeconds', video_details.get('lengthSeconds')
                )
            )
        except ValueError:
            pass

        self.view_count = convert_number_string(
            video_details.get('viewCount', 0)
        )

        if microformat.get('publishDate'):
            self.published_timestamp = dateutil_parser.parse(
                microformat['publishDate']
            )

        if microformat.get('uploadDate'):
            self.uploaded_timestamp = dateutil_parser.parse(
                microformat['uploadDate']
            )

        if microformat.get('category'):
            self.categories | set(microformat.get('category', []))

        self.default_audio_language = microformat.get(
            'defaultAudioLanguage'
        )

        self.is_family_safe = microformat.get('isFamilySafe', False)

        self.privacy_status = microformat.get(
            'isUnlisted', self.privacy_status or 'public')

        self.is_live = video_details.get(
            'isLive', video_details.get('isLiveContent', False)
        )

        results: str = initial_data.get('contents', {}).get(
                'twoColumnWatchNextResults', {}).get('secondaryResults', '')
        if (self.duration and self.duration < 60
                and microformat.get('isShortsEligible', False)
                and 'reelShelfRenderer' in results):
            self.is_short = True

        self.keywords = self.keywords | set(video_details.get('keywords', []))

        self.thumbnails = self.thumbnails | YouTubeVideo._parse_thumbnails(
            None, video_details.get('thumbnail', {}).get('thumbnails', []) +
            microformat.get('thumbnail', {}).get('thumbnails', [])
        )

        self.age_restricted = self._check_age_restriction(
            player_response.get('playabilityStatus', {})
        )

        self.embedable = \
            microformat.get('embed', {}).get('iframeUrl') is not None

        if microformat.get('hasYpcMetadata'):
            self.license = 'youtube'

    @staticmethod
    def _parse_thumbnails(label: str | None,
                          thumbnail_data: list[dict[str, str | int]]
                          ) -> dict[str, YouTubeThumbnail]:
        '''
        Parse thumbnail URLs without downloading
        '''

        thumbnails: dict[str, YouTubeThumbnail] = {}
        thumb_list: list[YouTubeThumbnail] = []
        for thumbnail in thumbnail_data or []:
            thumbnail = YouTubeThumbnail(None, thumbnail)
            if thumbnail.size and thumbnail.url:
                # We only want to store thumbnails for which
                # we know the size and have a URL
                thumb_list.append(thumbnail)
            else:
                _LOGGER.debug(
                    f'Not importing thumbnail without size '
                    f'({thumbnail.size}) or URL ({thumbnail.url})'
                )

        if not thumb_list:
            return {}

        # Sort by width and assign to standard sizes
        thumb_list = sorted(
            thumb_list, key=lambda x: (int(x.preference or 0), x.width)
        )

        # size_names: list[str] = [
        #     'default', 'medium', 'high', 'standard', 'maxres'
        # ]
        seen_urls: set[str] = set()

        thumb: YouTubeThumbnail
        for thumb in thumb_list:
            if thumb.url in seen_urls:
                continue
            seen_urls.add(thumb.url)

            if not label:
                label = f'video_{thumb.width}x{thumb.height}'

            if label not in thumbnails:
                thumbnails[label] = thumb

        return thumbnails

    def _check_age_restriction(self, playability: dict) -> bool:
        '''Check if video is age-restricted'''
        reason: str = playability.get('reason', '')
        if 'age' in reason.lower() or 'sign in' in reason.lower():
            return True

        # Check for age gate
        if playability.get('status') == 'LOGIN_REQUIRED':
            return True

        return False

    async def _scrape_video(self, ingest_videos: bool, channel_name: str,
                            channel_thumbnail: YouTubeThumbnail | None
                            ) -> None:
        '''
        Collects data about a video by scraping the webpage for the video.
        This method does not download the video itself.

        :param video_id: YouTube video ID
        :param ingest_videos: whether the video will be ingested
        :param channel_name: Name of the channel that we are scraping
        :param channel_thumbnail: Thumbnail for the creator of the video
        page
        '''

        log_data: dict[str, str] = {
            'channel': channel_name,
            'video_id': self.video_id,
            'ingest_status': self.ingest_status.value
        }

        if not self.browse_client:
            raise ByodaRuntimeError(
                'No browse_client available for scraping video'
            )

        self.channel_thumbnail_url = \
            channel_thumbnail.url if channel_thumbnail else None
        self.channel_thumbnail_asset = channel_thumbnail

        try:
            _LOGGER.debug('Scraping YouTube video', extra=log_data)
            video_info: dict[str, any] = self.browse_client.extract_info(
                self.url, download=False
            )
            if video_info:
                _LOGGER.debug('Collected info for video', extra=log_data)
            else:
                sleepy_time: int = randrange(10, 30)
                log_data['sleep_seconds'] = sleepy_time
                await sleep(sleepy_time)
                raise ByodaValueError(
                    'Video scrape failed, no info returned',
                    loglevel=logging.INFO, extra=log_data
                )
        except DownloadError as exc:
            sleepy_time: int = randrange(2, 5)
            self._transition_state(IngestStatus.UNAVAILABLE)
            log_data['ingest_status'] = self.ingest_status.value
            self._transition_state(IngestStatus.UNAVAILABLE)
            await sleep(sleepy_time)
            raise ByodaRuntimeError(
                'Failed to extract info for video, sleeping',
                extra=log_data | {'seconds': sleepy_time},
                loglevel=logging.INFO
            ) from exc
        except Exception as exc:
            sleepy_time: int = randrange(10, 30)
            await sleep(sleepy_time)
            raise ByodaException(
                'Failed to extract info for video, sleeping',
                extra=log_data | {'seconds': sleepy_time},
                loglevel=logging.INFO
            ) from exc

        self.channel = video_info.get('channel')

        self.is_live = self.is_live or video_info.get('is_live')
        if self.is_live:
            _LOGGER.debug('Skipping live video', extra=log_data)
            return

        self.embedable = self.embedable or video_info.get(
            'playable_in_embed', True
        )
        if not (self.embedable or ingest_videos):
            _LOGGER.debug('Skipping non-embedable video', extra=log_data)
            return

        self.description = self.description or video_info.get('description')
        self.title = self.title or video_info.get('title')
        self.view_count = self.view_count or video_info.get('view_count')
        self.like_count = self.like_count or video_info.get('like_count')
        self.comment_count = self.comment_count or video_info.get(
            'comment_count'
        )
        self.long_title = self.long_title or video_info.get('fulltitle')
        self.is_live = self.is_live or video_info.get('is_live')
        self.was_live = self.was_live or video_info.get('was_live')
        self.availability = video_info.get('availability')
        self.duration = self.duration or video_info.get('duration')
        self.tags = self.tags | set(video_info.get('tags', []))
        self.categories = self.categories | set(video_info.get('categories', []))
        self.default_audio_language = video_info.get('language')
        self.age_limit = self.age_limit or video_info.get('age_limit', 0)
        self.heatmaps = video_info.get('heatmaps', [])

        try:
            if (not ingest_videos
                    and self.age_limit and int(self.age_limit) >= 18):
                _LOGGER.debug(
                    'Video is for 18+ videos and can not be embedded',
                    extra=log_data
                )
                return
        except ValueError:
            _LOGGER.debug(
                'Age limit is not an integer: '
                f'{self.age_limit, type(self.age_limit)}',
                extra=log_data
            )

        for language_code, captions in video_info.get(
                'automatic_captions', {}).items():
            for caption in captions:
                caption = YouTubeCaption(
                    language_code, True, caption
                )
                self.captions.append(caption)

        for language_code, captions in video_info.get(
                'subtitles', {}).items():
            for caption in captions:
                caption = YouTubeCaption(
                    language_code, False, caption
                )
                self.captions.append(caption)

        self.published_timestamp = dateutil_parser.parse(
            video_info.get('upload_date', self.published_timestamp)
        )
        self.channel_id = video_info.get('channel_id')

        self.thumbnails = YouTubeVideo._parse_thumbnails(
            None, video_info.get('thumbnails') or []
        )

        for chapter_data in video_info.get('chapters') or []:
            chapter = YouTubeVideoChapter(chapter_data)
            self.chapters.append(chapter)

        self.screen_orientation_horizontal = self._parse_encoding_profiles(
            video_info
        )

        _LOGGER.debug(
            'Parsed all available data for video', extra=log_data
        )

    def _parse_encoding_profiles(self, video_info: dict[str, any]) -> bool:
        max_height: int = 0
        max_width: int = 0
        for format_data in video_info.get('formats') or []:
            yt_format: YouTubeFormat = YouTubeFormat.from_dict(format_data)
            if yt_format.height and yt_format.height > max_height:
                max_height = yt_format.height
            if yt_format.width and yt_format.width > max_width:
                max_width = yt_format.width
            self.encoding_profiles[yt_format.format_id] = yt_format

        self.screen_orientation_horizontal = True
        if max_height > max_width:
            self.screen_orientation_horizontal = False

        return self.screen_orientation_horizontal

    def _is_short(self, initial_data: dict) -> bool:
        '''
        Determine if the video is a YouTube Short

        :param video_details: videoDetails section from the player response
        :param initial_data: ytInitialData extracted from the HTML page
        :returns: True if the video is a YouTube Short, False otherwise
        '''

        if self.screen_orientation_horizontal is True:
            return False

        if self.duration and self.duration > 60:
            return False

        # Check for Shorts-specific markers in initial data
        try:
            # Look for reelWatchEndpoint or shorts indicators
            contents = initial_data.get('contents', {})
            if 'twoColumnWatchNextResults' in contents:
                results = contents['twoColumnWatchNextResults']
                secondary = results.get('secondaryResults', {})
                if 'reelShelfRenderer' in str(secondary):
                    return True
        except (KeyError, TypeError):
            pass

        return False

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

    @staticmethod
    def get_publish_datetime_from_api(data) -> datetime:
        '''
        Extract the publication date/time from the data returned by the
        YouTube Data API

        :param data: data as returned by the YouTube Data API
        :returns: the publication date/time
        '''

        snippet: dict = data.get('snippet')
        if not snippet:
            raise ByodaValueError(
                'Invalid data from YouTube API: no snippet'
            )

        if 'publishedAt' not in snippet:
            raise ByodaValueError(
                'Invalid data from YouTube API: no publishedAt'
            )

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
            'channel': self.channel,
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
            'creator': self.channel,
            'publisher': self.publisher,
            'publisher_asset_id': self.video_id,
            'title': self.title,
            'contents': self.description,
            'keywords': list(self.keywords),
            'annotations': list(self.annotations),
            'categories': list(self.categories),
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
        self, member: Member, ingest_asset: bool,
        video_table: Table, bento4_directory: str = None,
        moderate_request_url: str | None = None,
        moderate_jwt_header: str = None, moderate_claim_url: str | None = None,
        custom_domain: str | None = None, _test_asset_dir: str | None = None
    ) -> bool:
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
        :param _test_asset_dir: location of test asset to avoid downloading
        :returns: True if the video was added, False if it already existed
        :raises: ByodaValueError if storage_driver is not set
        '''

        log_data: dict[str, str] = {
            'video_id': self.video_id, 'channel': self.channel,
            'channel_id': self.channel_id,
            'channel_thumbnail': self.channel_thumbnail_url,
            'ingest_status': self.ingest_status.value
        }

        if not self.storage_driver:
            raise ByodaValueError(
                'storage_driver must be set if ingest_asset is True',
                extra=log_data, loglevel=_LOGGER.error
            )

        update: bool = False
        claim_request: ClaimRequest | None = None
        log_data['ingest_status'] = self.ingest_status.value
        if self.ingest_status != IngestStatus.UNAVAILABLE:
            # We import thumbnails regardless of ingress setting so that
            # the browser doesn't have to download these from YouTube, which
            # may improve privacy
            await self._ingest_thumbnails(
                self.storage_driver, member, custom_domain=custom_domain
            )

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
                        member, self.storage_driver, video_table,
                        bento4_directory, custom_domain=custom_domain,
                        _test_asset_dir=_test_asset_dir
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

                    self.monetizations: Monetizations = \
                        Monetizations.from_monetization_instance(
                            BurstMonetization()
                        ).as_dict()

                    # We now set state to PUBLISHED because we need that value
                    # to be written to the database
                    if self.ingest_status != IngestStatus.UNAVAILABLE:
                        self._transition_state(IngestStatus.PUBLISHED)
                        log_data['ingest_status'] = self.ingest_status.value

                except (ValueError, ByodaRuntimeError) as exc:
                    if config.test_case:
                        _LOGGER.debug(
                            'Test case, not bothering about moderation failure'
                        )
                    else:
                        raise ByodaRuntimeError(
                            'Moderation request for YouTube video failed',
                            extra=log_data, loglevel=logging.INFO
                        ) from exc

        asset: dict[str, any] = {}
        for field, mapping in YouTubeVideo.DATASTORE_FIELD_MAPPINGS.items():
            value: any = getattr(self, field)
            if value is not None:
                if isinstance(value, Enum):
                    asset[mapping] = value.value
                elif isinstance(value, set):
                    asset[mapping] = list(value)
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
                self.storage_driver.save(
                    f'claim_requests/pending/{self.asset_id}',
                    orjson.dumps(claim_request, orjson.OPT_INDENT_2)
                )

        asset[YouTubeVideo.DATASTORE_CLASS_NAME_THUMBNAILS] = [
            thumbnail.as_dict() for thumbnail in self.thumbnails.values() or []
        ]

        asset[YouTubeVideo.DATASTORE_CLASS_NAME_CHAPTERS] = [
            chapter.as_dict() for chapter in self.chapters or []
        ]

        asset['encoding_profiles'] = list(self.encoding_profiles.keys())
        asset['video_captions'] = [
            caption.as_dict() for caption in self.captions or []
        ]

        network: Network = member.network
        schema: Schema = member.schema
        data_class: SchemaDataArray = \
            schema.data_classes[YouTubeVideo.DATASTORE_CLASS_NAME]

        # For test cases, we need to set up authentication for use with
        # FastAPI APP instead of making an actual HTTP call against a
        # pod server
        app: FastAPI | None = None
        auth_header: dict[str, str] | None = None
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
        try:
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
        except Exception as exc:
            raise ByodaRuntimeError(
                f'Failed to ingest video with query_id {query_id}',
                extra=log_data, loglevel=logging.DEBUG
            ) from exc

        _LOGGER.info(
            'Added YouTube video', extra=log_data
        )

        return not update

    def _recreate_work_dir(self) -> str:
        '''
        Recreates the work directory for the video

        :returns: path to the work directory
        :raises: ByodaRuntimeError if the work directory can not be created
        '''

        if not self.storage_driver:
            raise ByodaRuntimeError(
                'No storage driver available to create work directory',
                log_extra={
                    'video_id': self.video_id, 'work_dir': self._work_dir
                }
            )

        try:
            shutil.rmtree(self._work_dir, ignore_errors=True)
            os.makedirs(self._work_dir, exist_ok=True)
        except OSError as exc:
            raise ByodaValueError(
                f'Failed to create work directory {self._work_dir}',
                log_extra={
                    'video_id': self.video_id, 'work_dir': self._work_dir
                }
            ) from exc

        return self._work_dir

    def download(self, _test_asset_dir: str | None = None) -> str:
        '''
        Downloads the video and audio streams of the video. Stores the
        different files in work_directory. Will create 'work_dir' if it
        does not exist.

        The directory used to temporarily store the downloaded video files
        is defined by self.download_client so this method does not
        support concurrent downloads of videos using the same
        self.download_client.

        :returns: directory where the video was downloaded
        :raises: OSError if work_dir exists and is not empty
        '''

        log_data: dict[str, str] = {
            'video_id': self.video_id, 'channel': self.channel,
            'ingest_status': self.ingest_status.value
        }

        self._transition_state(IngestStatus.DOWNLOADING)
        log_data['ingest_status'] = self.ingest_status.value

        self._recreate_work_dir()
        if config.test_case and _test_asset_dir is not None:
            copytree(_test_asset_dir, self._work_dir,)

            _LOGGER.debug(
                'Skipping download of video in test case', extra=log_data
            )
            return self._work_dir

        try:
            _LOGGER.debug(
                f'Downloading YouTube video to {self._work_dir} started',
                extra=log_data
            )
            self.download_client.download([self.url])
            _LOGGER.debug(
                f'Download of YouTube video to {self._work_dir} completed',
                extra=log_data
            )
        except (DownloadError, Exception) as exc:
            raise ByodaValueError(
                'Failed to download YouTube video', loglevel=logging.INFO,
                extra=log_data
            ) from exc

        return self._work_dir

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
        bento4_directory: str, custom_domain: str | None = None,
        _test_asset_dir: str | None = None
    ) -> bool | None:
        '''
        Downloads to audio and video files of the asset and stores them
        on object storage

        :param storage_driver: The storage driver to store the video with
        :param ingest_asset: should the A/V tracks of the asset be downloaded
        :param video_table: Table for persisting videos
        :param bento4_directory: directory where to find the BenTo4 MP4
        packaging tool
        :param custom_domain: custom domain to use for the video URL
        :param _test_asset_dir: directory where to find the test asset so
        that it does not need to be downloaded
        :returns: True if the video was updated, False if it was created
        :raises: ByodaValueError if the ingest status of the video is invalid
        '''

        server: PodServer = config.server

        log_data: dict[str, str] = {
            'video_id': self.video_id, 'channel': self.channel,
            'ingest_status': self.ingest_status.value,
            'cdn_fqdn': server.cdn_fqdn,
            'cdn_origin_site_id': server.cdn_origin_site_id,
            'work_dir': self._work_dir
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
                    video_data[0][0].get('ingest_status')

                log_data['ingest_status'] = current_status
                if not isinstance(current_status, IngestStatus):
                    current_status = IngestStatus(current_status)
            except ValueError as exc:
                raise ByodaValueError(
                    f'Video has an invalid ingest status, {current_status}, '
                    'skipping ingest', extra=log_data
                ) from exc

            if current_status == IngestStatus.PUBLISHED:
                return False

            if current_status == IngestStatus.EXTERNAL:
                update = True

        try:
            self.download(_test_asset_dir=_test_asset_dir)

            self.package_streams(self._work_dir, bento4_dir=bento4_directory)

            await self.upload(self._work_dir, storage_driver)

            tree: ByoMerkleTree = ByoMerkleTree.calculate(
                directory=self._work_dir
            )
            self.merkle_root_hash = tree.as_string()

            tree_filename: str = tree.save(self._work_dir)
            await storage_driver.copy(
                f'{self._work_dir}/{tree_filename}',
                f'{self.asset_id}/{tree_filename}',
                storage_type=StorageType.RESTRICTED, exist_ok=True
            )
        except ByodaRuntimeError:
            self._transition_state(IngestStatus.UNAVAILABLE)
            raise
        except Exception as exc:
            self._transition_state(IngestStatus.UNAVAILABLE)
            raise ByodaException(
                'Ingesting asset for YouTube video failed',
                extra=log_data
            ) from exc
        finally:
            if not config.test_case:
                self._recreate_work_dir()

        if server.cdn_fqdn and server.cdn_origin_site_id:
            _LOGGER.debug(
                'Using CDN Origin for thumbnail', extra=log_data
            )
            self.url: str = Paths.RESTRICTED_ASSET_CDN_URL.format(
                cdn_fqdn=server.cdn_fqdn,
                cdn_origin_site_id=server.cdn_origin_site_id,
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
    ) -> int:
        '''
        Ingests the thumbnails of the video and its creator

        :param storage_driver: the storage driver to upload the video with
        :param member: the membership for the service
        :returns: number of ingested thumbnails
        '''

        log_data: dict[str, str] = {
            'video_id': self.video_id,
            'channel': self.channel,
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
                raise
            finally:
                self._delete_tempdir(tmp_dir)

        tmp_dir: str = self._create_tempdir(storage_driver)
        if self.channel_thumbnail_asset:
            _LOGGER.debug(
                'Starting ingest of creator thumbnail from '
                f'{self.channel_thumbnail_asset.url}',
                extra=log_data
            )
            try:
                self.channel_thumbnail = \
                    await self.channel_thumbnail_asset.ingest(
                        self.asset_id, storage_driver, member, tmp_dir,
                        custom_domain=custom_domain
                    )
                thumbnails_counter += 1
            except ByodaRuntimeError:
                self._transition_state(IngestStatus.UNAVAILABLE)
                raise
            finally:
                self._delete_tempdir(tmp_dir)

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
            'channel': self.channel,
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
        '''
        Gets the path to a temporary directory for downloading
        and processing the video. The directory is not created.

        :param storage_driver:
        :returns: the path to the temporary directory
        '''

        tmp_dir: str = storage_driver.local_path + 'tmp/'
        if self.video_id:
            tmp_dir += f'ytvideo_{self.video_id}/'
        else:
            tmp_dir += f'ytvideo_{uuid4()[0:6]}/'

        return tmp_dir

    def _create_tempdir(self, storage_driver: FileStorage) -> str:
        '''
        Creates a temporary directory for downloading and processing
        the video

        :param storage_driver:
        :returns: the path to the temporary directory

        '''

        tmp_dir: str = self._get_tempdir(storage_driver)

        os.makedirs(tmp_dir, exist_ok=True)

        return tmp_dir

    def _delete_tempdir(self, tmp_dir: str) -> None:
        '''
        Deletes the temporary directory for downloading and processing
        the video

        :param tmp_dir: path to the temporary directory to be deleted
        '''

        shutil.rmtree(tmp_dir, ignore_errors=True)

    def package_streams(self, work_dir: str, bento4_dir: str = BENTO4_DIR
                        ) -> None:
        '''
        Creates MPEG-DASH and HLS manifests for the video and audio streams
        in work_dir
        '''

        log_extra: dict[str, str] = {
            'video_id': self.video_id,
            'channel': self.channel,
            'asset_id': self.asset_id,
            'ingest_status': self.ingest_status.value
        }

        if not bento4_dir:
            bento4_dir = BENTO4_DIR

        self._transition_state(IngestStatus.PACKAGING)

        # These encoding profiles will replace the existing profiles
        # that are based on what YouTube made available
        self._review_encoding_profiles(work_dir, log_extra)

        # We create manifests for each of the encoding profiles
        pkg_dirs: list[str] = []
        for category in sorted(EncodingCategory):
            pkg_dir: str | None = self._package_category_streams(
                category, work_dir, bento4_dir, log_extra
            )
            if pkg_dir:
                pkg_dirs.append(pkg_dir)

        self._consolidate_category_files(pkg_dirs, work_dir)

        self._create_default_manifests(work_dir, log_extra=log_extra)

    def _review_encoding_profiles(
        self, work_dir: str, log_extra: dict[str, any]
    ) -> dict[str, dict[str, any]]:
        '''
        Only include profiles that have been downloaded by YT-DLP
        '''

        all_encoding_profiles: dict[str, YouTubeFormat] = copy(
            self.encoding_profiles
        )
        self.encoding_profiles = {}
        filename: str
        for filename in os.listdir(work_dir):
            if not filename.startswith('asset-'):
                continue

            profile_number: str = YouTubeVideo._get_profile(filename)
            if profile_number in all_encoding_profiles:
                self.encoding_profiles[profile_number] = all_encoding_profiles[
                    profile_number
                ]
            else:
                _LOGGER.debug(
                    f'Did not expect encoding profile #{profile_number}',
                    extra=log_extra
                )

    def _create_default_manifests(self, work_dir: str,
                                  log_extra: dict[str, any]) -> None:
        '''
        Make sure there are default manifests for the video and audio
        '''

        if os.path.exists(f'{work_dir}/video.mpd-1080p'):
            _LOGGER.debug('Defaulting to 1080p', extra=log_extra)
            shutil.copy(
                f'{work_dir}/video.mpd-1080p', f'{work_dir}/video.mpd'
            )
            shutil.copy(
                f'{work_dir}/video.m3u8-1080p', f'{work_dir}/video.m3u8'
            )
        elif os.path.exists(f'{work_dir}/video.mpd-720p'):
            _LOGGER.debug('Defaulting to 720p', extra=log_extra)
            shutil.copy(
                f'{work_dir}/video.mpd-720p', f'{work_dir}/video.mpd'
            )
            shutil.copy(
                f'{work_dir}/video.m3u8-720p', f'{work_dir}/video.m3u8'
            )
        elif os.path.exists(f'{work_dir}/video.mpd-SD'):
            _LOGGER.debug('Defaulting to SD', extra=log_extra)
            shutil.copy(
                f'{work_dir}/video.mpd-SD', f'{work_dir}/video.mpd'
            )
            shutil.copy(
                f'{work_dir}/video.m3u8-SD', f'{work_dir}/video.m3u8'
            )
        else:
            _LOGGER.debug('No target for default manifest', extra=log_extra)

    def _package_category_streams(
        self, category: EncodingCategory, work_dir: str, bento4_dir: str,
        log_extra: dict[str, any]
    ) -> str | None:
        '''
        Creates MPEG-DASH and HLS manifests for the video and audio streams
        for the given encoding category

        :returns: the directory where the packaged files are located
        '''

        label: str = category.label()
        log_extra['content_category'] = label

        file_names: list[str] = [
            file_name for file_name in os.listdir(work_dir)
            if not file_name.endswith('.json')
        ]
        log_extra['files'] = file_names
        _LOGGER.debug(
            'Packaging MPEG-DASH and HLS manifests for '
            f'files: {", ".join(file_names)}', extra=log_extra
        )

        if not self._has_tracks(category):
            _LOGGER.debug('No tracks for category', extra=log_extra)
            return

        category_files: set[str] = set()
        for filename in file_names:
            if filename.startswith('packaged-'):
                continue

            profile_number: str = YouTubeVideo._get_profile(filename)
            include: bool = False
            if YouTubeVideo._is_audio_track(filename):
                log_extra['profile'] = profile_number

                if (TARGET_AUDIO_STREAMS[profile_number]['category'].value <=
                        category.value):
                    include = True
            elif YouTubeVideo._is_video_track(filename):
                if (TARGET_VIDEO_STREAMS[profile_number]['category'].value <=
                        category.value):
                    include = True

            if include:
                category_files.add(f'{work_dir}/{filename}')
                _LOGGER.debug(
                    'Added encoding profile to category',
                    extra=log_extra
                )

        profile_dir: str = f'{work_dir}/packaged-{label}'
        # https://www.bento4.com/documentation/mp4dash/
        # Would have liked to use '--no-media' flag but it throws and error
        result: subprocess.CompletedProcess[str] = subprocess.run(
            [
                f'{bento4_dir}/bin/mp4dash',
                '--no-split', '--use-segment-list',
                '--use-segment-timeline',
                '--mpd-name', f'video.mpd-{label}',
                '--hls',
                '--hls-master-playlist-name', f'video.m3u8-{label}',
                '-o', f'{profile_dir}',
                *category_files
            ],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(
                f'Packaging failed for asset {self.video_id}: '
                f'{result.stderr}'
            )

        _LOGGER.debug(
            'Packaging successful for category', extra=log_extra
        )
        self._delete_dupe_bento4_media_file(profile_dir, work_dir)

        return profile_dir

    def _delete_dupe_bento4_media_file(self, profile_dir: str, work_dir: str
                                       ) -> None:
        # The '--no-media' flag does not work with the mp4dash command so
        # we end up with duplicate A/V files, and we can delete the dupes
        # from the profile-specific directory
        for filename in os.listdir(profile_dir):
            if os.path.exists(f'{work_dir}/{filename}'):
                os.remove(f'{profile_dir}/{filename}')

    def _consolidate_category_files(self, profile_dirs: list[str], work_dir
                                    ) -> None:
        '''
        Consolidate all the outputs from the Bento4 packaging tool into
        one directory.

        '''

        profile_dir: str
        for profile_dir in profile_dirs:
            for filename in os.listdir(profile_dir):
                if not os.path.exists(f'{work_dir}/{filename}'):
                    shutil.move(f'{profile_dir}/{filename}', work_dir)
                else:
                    os.remove(f'{profile_dir}/{filename}')

            os.rmdir(profile_dir)

    def _has_tracks(self, encoding_category: EncodingCategory) -> bool:
        '''
        Checks if the video has tracks for the encoding category

        :param encoding_category: the encoding category
        :returns: whether the video has tracks for the encoding category
        '''

        for profile in self.encoding_profiles:
            profile_specs: dict[str, any] = TARGET_VIDEO_STREAMS.get(profile)
            if (profile_specs
                    and profile_specs.get('category') == encoding_category):
                return True

        return False

    @staticmethod
    def _is_video_track(filename: str) -> bool:
        return filename.endswith('.mp4')

    @staticmethod
    def _is_audio_track(filename: str) -> bool:
        return filename.endswith('.m4a')

    @staticmethod
    def _get_profile(filename: str) -> str:
        return filename.split('.')[-2]
