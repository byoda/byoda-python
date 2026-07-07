'''
Model a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import os
import shutil
import logging
import subprocess

from copy import copy
from enum import Enum
from uuid import UUID
from uuid import uuid4
from shutil import copytree
from logging import Logger
from logging import getLogger
from datetime import datetime
from datetime import timezone

import orjson

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

from byoda.servers.pod_server import PodServer

from byoda.exceptions import ByodaException, ByodaValueError
from byoda.exceptions import ByodaRuntimeError

from byoda import config

from .youtube_format import YouTubeFormat
from .youtube_thumbnail import YouTubeThumbnail
from .youtube_streams import EncodingCategory
from .youtube_streams import TARGET_AUDIO_STREAMS
from .youtube_streams import TARGET_VIDEO_STREAMS

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
        'channel_url': 'channel_url',
        'channel_country': 'channel_country',
        'channel_is_verified': 'channel_is_verified',
        'channel_follower_count': 'channel_follower_count',
        'channel_thumbnail_url': 'channel_thumbnail',
        'long_title': 'long_title',
        'uploaded_timestamp': 'uploaded_timestamp',
        'published_timestamp': 'published_timestamp',
        'availability': 'availability',
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
        'media_type': 'media_type',
        'is_tv_film_video': 'is_tv_film_video',
        'embed_url': 'embed_url',
        'embedable': 'embedable',
        'aspect_ratio': 'aspect_ratio',
        'available_country_codes': 'available_country_codes',
        'heatmaps': 'heatmaps',
        'subtitles': 'subtitles',
        'automatic_captions': 'automatic_captions',
        'formats': 'formats',
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
        'age_restricted': 'age_restricted',
        'privacy_status': 'privacy_status',
    }

    def __init__(self,
                 video_id: str | None = None,
                 consent_cookies: dict[str, str] = {},
                 download_client: YoutubeDL | None = None,
                 storage_driver: FileStorage | None = None) -> None:

        # Consent cookies needed for YouTubeClient and yt-dlp
        self.consent_cookies: dict[str, str] = consent_cookies
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
        self.channel_url: str | None = None
        self.channel_country: str | None = None
        self.channel_is_verified: bool | None = None
        self.channel_follower_count: int | None = None
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
        self.media_type: str | None = None
        self.is_tv_film_video: bool | None = None
        self.aspect_ratio: float | None = None
        self.available_country_codes: list[str] = []

        self.age_limit: int = 0
        self.age_restricted: bool = False
        self.is_family_safe: bool | None = None
        self.screen_orientation_horizontal: bool = True

        # Duration of the video in seconds
        self.duration: int | None = None

        self.chapters: list[YouTubeVideoChapter] = []
        self.captions: list[YouTubeCaption] = []
        self.heatmaps: list[dict[str, float]] = []
        self.subtitles: dict[str, list[dict[str, any]]] = {}
        self.automatic_captions: dict[str, list[dict[str, any]]] = {}
        self.formats: dict[str, any] = {}
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

        self.ydl: YoutubeDL | None = None

        if storage_driver:
            self.storage_driver: FileStorage = storage_driver
            self._work_dir: str = self._get_tempdir(storage_driver)

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
