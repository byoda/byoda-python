'''
Model a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import shutil
import logging
import subprocess

from enum import Enum
from uuid import UUID, uuid4
from dataclasses import dataclass
from datetime import datetime, timezone
from dateutil import parser as dateutil_parser

import orjson

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from byoda.datamodel.member import Member

from byoda.datastore.data_store import DataStore
from byoda.datamodel.datafilter import DataFilterSet

from byoda.storage.filestorage import FileStorage

from byoda.datatypes import StorageType
from byoda.datatypes import IngestStatus

from byoda.util.paths import Paths

_LOGGER = logging.getLogger(__name__)

BENTO4_DIR: str = '/podserver/bento4'

# These are the MPEG-DASH AV1 and H.264 streams that we want to download. If a video
# doest not have one of the wanted streams, then we will try to download the replacement.
# We are currently not attempting to download 8k streams
TARGET_VIDEO_STREAMS = {
    '701': {'resolution': '2160p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '401'},
    '700': {'resolution': '1440p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '400'},
    '699': {'resolution': '1080p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '399'},
    '698': {'resolution': '720p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '398'},
    '697': {'resolution': '480p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '397'},
    '696': {'resolution': '360p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '396'},
    '695': {'resolution': '240p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '395'},
    '694': {'resolution': '144p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '394'},
    '398': {'resolution': '720p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '298'},
    '402': {'resolution': '4320p', 'codec': 'AV1 HFR', 'wanted': False, 'replacement': None},
    '571': {'resolution': '4320p', 'codec': 'AV1 HFR', 'wanted': False, 'replacement': None},
    '401': {'resolution': '2160p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '305'},
    '400': {'resolution': '1440p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '304'},
    '399': {'resolution': '1080p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '299'},
    '397': {'resolution': '480p', 'codec': 'AV1', 'wanted': True, 'replacement': '135'},
    '396': {'resolution': '360p', 'codec': 'AV1', 'wanted': True, 'replacement': '134'},
    '395': {'resolution': '240p', 'codec': 'AV1', 'wanted': True, 'replacement': '133'},
    '394': {'resolution': '144p', 'codec': 'AV1', 'wanted': True, 'replacement': '160'},
    '305': {'resolution': '2160p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '266'},
    '304': {'resolution': '1440p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '264'},
    '299': {'resolution': '1080p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '137'},
    '298': {'resolution': '720p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '136'},
    '266': {'resolution': '2160p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '264': {'resolution': '1440p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '137': {'resolution': '1080p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '136': {'resolution': '720p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '135': {'resolution': '480p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '134': {'resolution': '360p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '133': {'resolution': '240p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '160': {'resolution': '144p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
}

# These are the MPEG-DASH MP4 audio streams that we want to download.
TARGET_AUDIO_STREAMS = {
    '599': {'codec': 'mp4a HE v1 32kbps', 'wanted': True, 'replacement': None},
    '139': {'codec': 'mp4a HE v1 48kbps', 'wanted': True, 'replacement': None},
    '140': {'codec': 'mp4a AAC-LC 128kbps', 'wanted': True, 'replacement': None},
    '141': {'codec': 'mp4a AAC-LC 256kbps', 'wanted': True, 'replacement': None},
}


@dataclass
class Annotation:
    value: str
    key: str | None = None

class YouTubeThumbnailSize(Enum):
    # flake8: noqa=E221
    DEFAULT         = 'default'
    MEDIUM          = 'medium'
    HIGH            = 'high'


class YouTubeFragment:
    '''
    Models a fragment of a YouTube video or audio track
    '''

    def __init__(self):
        self.url: str | None = None
        self.duration: float | None = None
        self.path: str | None = None

    def as_dict(self):
        '''
        Returns a dict representation of the fragment
        '''

        return {
            'url': self.url,
            'duration': self.duration,
            'path': self.path
        }

    @staticmethod
    def from_dict(data: dict[str, str | float]):
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

    def __init__(self):
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

    def __str__(self):
        return (
            f'YouTubeFormat('
            f'{self.format_id}, {self.format_note}, {self.ext}, '
            f'{self.protocol}, {self.audio_codec}, {self.video_codec}, '
            f'{self.container}, {self.width}, {self.height}, {self.fps}, '
            f'{self.resolution}, '
            f'{self.audio_ext}, {self.video_ext}'
            ')'
        )

    def as_dict(self):
        '''
        Returns a dict representation of the video
        '''

        data = {
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

    def from_dict(data: dict[str, any]):
        '''
        Factory using data retrieved using the 'yt-dlp' tool
        '''

        format = YouTubeFormat()
        format.format_id = data['format_id']
        format.format_note = data.get('format_note')
        format.ext = data.get('ext')
        format.protocol = data.get('protocol')
        format.audio_codec = data.get('acodec')
        if format.audio_codec.lower() == 'none':
            format.audio_codec = None

        format.video_codec = data.get('vcodec')
        if format.video_codec.lower() == 'none':
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
            fragment = YouTubeFragment.from_dict(fragment_data)
            format.fragments.append(fragment)

        return format


class YouTubeThumbnail:
    def __init__(self, size: str, data: dict):
        self.url: str = data.get('url')
        self.width: int = data.get('width', 0)
        self.height: int = data.get('height', 0)
        self.preference: int = data.get('preference')
        self.id: str = data.get('id')

        if size:
            self.size = YouTubeThumbnailSize(size)
        else:
            self.size = f'{self.width}x{self.height}'

    def __str__(self) -> str:
        if isinstance(self.size, YouTubeThumbnailSize):
            size = self.size.value
        else:
            size = self.size

        return f'{size}_{self.width}_{self.height}_{self.url}'

    def as_dict(self):
        '''
        Returns a dict representation of the thumbnail
        '''

        return {
            'url': self.url,
            'width': self.width,
            'height': self.height,
            'preference': self.preference,
            'size': self.size
        }

class YouTubeVideoChapter:
    def __init__(self, chapter_info: dict[str, float | str]):
        self.start_time: float = chapter_info.get('start_time')
        self.end_time: float = chapter_info.get('end_time')
        self.title: str = chapter_info.get('title')

    def as_dict(self):
        '''
        Returns a dict representation of the chapter
        '''

        return {
            'start_time': self.start_time,
            'end_time': self.end_time,
            'title': self.title
        }


class YouTubeVideo:
    VIDEO_URL: str = 'https://www.youtube.com/watch?v={video_id}'
    DATASTORE_CLASS_NAME: str = 'public_assets'
    DATASTORE_CLASS_NAME_THUMBNAILS: str = 'public_video_thumbnails'
    DATASTORE_CLASS_NAME_CHAPTERS: str = 'public_video_chapters'
    DATASTORE_FIELD_MAPPINGS: dict[str, str] = {
        'video_id': 'publisher_asset_id',
        'title': 'title',
        'description': 'contents',
        'published_time': 'published_timestamp',
        'url': 'asset_url',
        'channel_creator': 'creator',
        'url': 'asset_url',
        'created_time': 'created_timestamp',
        'asset_type': 'asset_type',
        'asset_id': 'asset_id',
        'locale': 'locale',
        'publisher': 'publisher',
        'ingest_status': 'ingest_status',
    }

    def __init__(self):
        self.video_id: str | None = None
        self.title: str | None = None
        self.kind: str | None = None
        self.long_title: str | None = None
        self.description: str | None = None
        self.channel_creator: str | None = None
        self.channel_id: str | None = None
        self.published_time: datetime | None = None
        self.published_time_info: str | None = None
        self.view_count: str | None = None
        self.url: str | None = None
        self.thumbnails: dict[YouTubeThumbnail] = {}
        self.duration: str | None = None
        self.is_live: bool | None = None
        self.was_live: bool | None = None
        self.availability: str | None = None
        self.embedable: bool | None = None
        self.age_limit: int | None = None

        # Duration of the video in seconds
        self.duration: int | None = None

        self.chapters: list[YouTubeVideoChapter] = []
        self.tags: list[str] = []

        # Data for the Byoda table with assets
        self.publisher = 'YouTube'
        self.asset_type: str = 'video'
        self.ingest_status: str = IngestStatus.NONE.value

        # This is the default profile. If we ingest the asset from
        # YouTube then this will be overwritten with info about the
        # YouTube formats
        self.encoding_profiles: dict[str, YouTubeFormat] = {}
        self.asset_id: UUID = uuid4()
        self.locale: str | None = None
        self.annotations: list[str] = []


        self.created_time: datetime = datetime.now(tz=timezone.utc)

        # If this has a value then it is not a video but a
        # playlist
        self.playlistId: str | None = None

    @staticmethod
    def scrape(video_id: str, cache_file: str = None):
        '''
        Collects data about a video by scraping the webpage for the video

        :param video_id: YouTube video ID
        :param cache_file: read data from file instead of scraping the web
        page
        '''

        video = YouTubeVideo()

        video.video_id = video_id
        video.url = YouTubeVideo.VIDEO_URL.format(video_id=video_id)

        ydl_opts = {'quiet': True}
        with YoutubeDL(ydl_opts) as ydl:
            video_info: dict[str, any] = {}
            if cache_file:
                try:
                    with open(cache_file, 'r') as file_desc:
                        video_info = orjson.loads(file_desc.read())
                except (OSError, orjson.JSONDecodeError):
                    _LOGGER.debug(f'Reading cache file {cache_file} failed')

            if not video_info:
                try:
                    _LOGGER.debug(f'Scraping YouTube video {video_id}')
                    video_info = ydl.extract_info(video.url, download=False)
                except DownloadError:
                    return None

            if cache_file and not os.path.exists(cache_file):
                with open(cache_file, 'w') as file_desc:
                    file_desc.write(
                        orjson.dumps(video_info, orjson.OPT_INDENT_2).decode('utf-8')
                    )

            video.description = video_info.get('description')
            video.title = video_info.get('title')
            video.view_count = video_info.get('view_count')
            video.duration = video_info.get('duration')
            video.long_title = video_info.get('fulltitle')
            video.is_live = video_info.get('is_live')
            video.was_live = video_info.get('was_live')
            video.availability = video_info.get('availability')
            video.embedable = video_info.get('embedable')
            video.age_limit = video_info.get('age_limit')
            video.view_count = video_info.get('view_count')
            video.duration = video_info.get('duration')
            video.annotations = video_info.get('tags')

            video.published_time: datetime = dateutil_parser.parse(
                video_info['upload_date']
            )
            video.channel_creator = video_info.get('channel', video.channel_creator)
            video.channel_id = video_info.get('channel_id')

            for thumbnail in video_info.get('thumbnails') or []:
                thumbnail = YouTubeThumbnail(None, thumbnail)
                if thumbnail.size:
                    # We only want to store thumbnails for which
                    # we know the size
                    video.thumbnails[thumbnail.size] = thumbnail

            for chapter in video_info.get('chapters') or []:
                chapter = YouTubeVideoChapter(chapter)
                video.chapters.append(chapter)

            for format_data in video_info.get('formats') or []:
                format = YouTubeFormat.from_dict(format_data)
                video.encoding_profiles[format.format_id] = format

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

    async def persist(self, member: Member, data_store: DataStore,
                      storage_driver: FileStorage, ingest_asset: bool,
                      already_ingested_videos: dict[str, dict],
                      bento4_directory: str = None) -> bool:
        '''
        Adds or updates a video in the datastore.

        :param member: The member
        :param data_store: The data store to store the videos in
        :param storage_driver: The storage driver to store the video with
        :param ingest_asset: should the A/V tracks of the asset be downloaded
        :param already_ingested_videos: dict with key the YouTube Video ID
        and as value the data retrieved for the asset from the data store.
        :param bento4_directory: directory where to find the BenTo4 MP4
        packaging tool
        :returns: True if the video was added, False if it already existed
        '''

        if ingest_asset and not storage_driver:
            raise ValueError(
                'storage_driver must be provided if ingest_asset is True'
            )

        update: bool = False
        if ingest_asset:
            if self.video_id in already_ingested_videos:
                update = True
                ingested_video: str = already_ingested_videos[self.video_id]
                current_status: str = ingested_video['ingest_status']
                if current_status == IngestStatus.PUBLISHED.value:
                    return False

            tmp_dir = storage_driver.local_path + 'tmp/' + self.video_id
            self.download(
                TARGET_VIDEO_STREAMS, TARGET_AUDIO_STREAMS, work_dir=tmp_dir
            )
            pkg_dir = self.package_streams(tmp_dir, bento4_dir=bento4_directory)

            for filename in os.listdir(pkg_dir):
                source = f'{pkg_dir}/{filename}'
                dest = f'{self.asset_id}/{filename}'
                _LOGGER.debug(
                    f'Copying {source} to {dest} on RESTRICTED storage'
                )

                await storage_driver.copy(
                    source, dest, storage_type=StorageType.RESTRICTED,
                    exist_ok=True
                )
            shutil.rmtree(tmp_dir)

            self.url: str = Paths.RESTRICTED_ASSET_CDN_URL.format(
                member_id=member.member_id, service_id=member.service_id,
                asset_id=self.asset_id, filename='video.mpd'
            )
            self.ingest_status = IngestStatus.PUBLISHED.value
        else:
            self.ingest_status = IngestStatus.EXTERNAL.value

        asset = {}
        for field, mapping in YouTubeVideo.DATASTORE_FIELD_MAPPINGS.items():
            value = getattr(self, field)
            if value:
                asset[mapping] = value



        if update:
            data_filter = DataFilterSet(
                {'publisher_asset_id': {
                    'eq': self.video_id}
                }
            )
            await data_store.delete(
                member.member_id, YouTubeVideo.DATASTORE_CLASS_NAME,
                data_filter_set=data_filter
            )
            asset_filter = DataFilterSet({'asset_id': {'eq': self.asset_id}})
            await data_store.delete(
                member.member_id, YouTubeVideo.DATASTORE_CLASS_NAME_THUMBNAILS,
                data_filter_set=asset_filter
            )
            await data_store.delete(
                member.member_id, YouTubeVideo.DATASTORE_CLASS_NAME_CHAPTERS,
                data_filter_set=asset_filter
            )

        await data_store.append(
            member.member_id, YouTubeVideo.DATASTORE_CLASS_NAME, asset
        )
        for thumbnail in self.thumbnails.values():
            data: dict = thumbnail.as_dict()
            data.update(
                {
                    'thumbnail_id': uuid4(),
                    'video_id': self.asset_id
                }
            )
            await data_store.append(
                member.member_id, YouTubeVideo.DATASTORE_CLASS_NAME_THUMBNAILS,
                data

            )
        for chapter in self.chapters:
            data: dict = chapter.as_dict()
            data.update(
                {
                    'thumbnail_id': uuid4(),
                    'video_id': self.asset_id
                }
            )
            await data_store.append(
                member.member_id, YouTubeVideo.DATASTORE_CLASS_NAME_CHAPTERS,
                data
            )
        _LOGGER.debug(f'Added YouTube video ID {self.video_id}')

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

        os.makedirs(work_dir, exist_ok=True)

        ydl_opts = {
            'quiet': True,
            'noprogress': True,
            'no_color': True,
            'format': ','.join(video_formats | audio_formats),
            'outtmpl': {'default': 'asset%(id)s.%(format_id)s.%(ext)s'},
            'paths': {'home': work_dir, 'temp': work_dir},
            'fixup': 'never',
        }

        with YoutubeDL(ydl_opts) as ydl:
            try:
                _LOGGER.debug(
                    f'Downloading YouTube video: {self.video_id} to {work_dir} started'
                )
                ydl.download([self.url])
                _LOGGER.debug(
                    f'Downloading YouTube video: {self.video_id} to {work_dir} completed'
                )
            except DownloadError:
                _LOGGER.info(f'Failed to download YouTube video {self.video_id}')
                return None

        return work_dir

    def filter_encoding_profiles(self, wanted_encoding_profiles: dict[str, dict[str, str | bool]]):
        '''
        Filters the encoding profiles to only include the wanted formats

        :param wanted_encoding_profiles: the wanted video or audio encoding profiles
        '''

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
                replacement = wanted_encoding_profiles[replacement].get('replacement')

        return included_profiles

    def package_streams(self, work_dir: str, bento4_dir: str = BENTO4_DIR) -> str:
        '''
        Creates MPEG-DASH and HLS manifests for the video and audio streams
        in work_dir

        :returns: the location of the packaged files
        '''

        if not bento4_dir:
            bento4_dir = BENTO4_DIR

        file_names: list[str] = [
            f'{work_dir}/{file_name}' for file_name in os.listdir(work_dir)
            if not file_name.endswith('.json')
        ]

        _LOGGER.debug(
            f'Packaging MPEG-DASH and HLS manifests for asset {self.video_id}'
            f'for files: {", ".join(file_names)}'
        )

        result = subprocess.run(
            [
                f'{bento4_dir}/bin/mp4dash',
                '--no-split', '--use-segment-list',
                '--mpd-name', 'video.mpd',
                '--hls', '--hls-master-playlist-name', 'video.m3u8',
                '-o', f'{work_dir}/packaged',

                *file_names
            ],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            _LOGGER.debug(f'Packaging successful for asset {self.video_id}')
        else:
            _LOGGER.debug(
                f'Packaging failed for asset {self.video_id}: {result.stderr}'
            )

        return f'{work_dir}/packaged'

