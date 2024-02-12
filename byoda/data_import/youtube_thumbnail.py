'''
Model a thumbnail of a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from enum import Enum
from uuid import uuid4
from uuid import UUID
from typing import Self
from logging import getLogger
from urllib.parse import urlparse, ParseResult

from httpx import AsyncClient as AsyncHttpClient

from byoda.datamodel.member import Member

from byoda.datatypes import ContentTypesByType

from byoda.storage.filestorage import FileStorage

from byoda.datatypes import StorageType

from byoda.util.logger import Logger

from byoda.util.paths import Paths

from byoda.exceptions import ByodaRuntimeError

_LOGGER: Logger = getLogger(__name__)

MAX_SPOOLED_FILE: int = 1024 * 1024
CHUNK_SIZE: int = 64 * 1024

class YouTubeThumbnailSize(Enum):
    # flake8: noqa=E221
    DEFAULT         = 'default'
    MEDIUM          = 'medium'
    HIGH            = 'high'


class YouTubeThumbnail:
    def __init__(self, size: str, data: dict,
                 display_hint: str | None = None) -> None:
        self.thumbnail_id: UUID = uuid4()
        self.url: str = data.get('url')
        self.width: int = data.get('width', 0)
        self.height: int = data.get('height', 0)
        self.id: str = data.get('id')
        self.youtube_url: str | None = None

        # What type of display the thumbnail was created for.
        # Only used for channel banners
        # For banners, YouTube uses: 'banner', 'tvBanner', 'mobileBanner'
        self.display_hint: str | None = display_hint

        self.preference: str = data.get('preference')
        if self.preference:
            self.preference = str(self.preference)
        else:
            self.preference = ''

        self.size: str | YouTubeThumbnailSize
        if size:
            self.size = YouTubeThumbnailSize(size)
        else:
            self.size = f'{self.width}x{self.height}'

    def __str__(self) -> str:
        size: int
        if isinstance(self.size, YouTubeThumbnailSize):
            size = self.size.value
        else:
            size = self.size

        return f'{size}_{self.width}_{self.height}_{self.url.rstrip("-mo")}'

    def __hash__(self) -> int:
        # YouTube has thumbnails with '-mo' appended to the end of the URL
        # that is the same as the thumbnail without it
        value: int = hash(
            f'{self.width}:{self.height}:{self.url}'
        )
        return value

    def __eq__(self, thumbnail: Self) -> bool:
        if not isinstance(thumbnail, YouTubeThumbnail):
            return False

        same: bool = (
            self.url == thumbnail.url
            or (
                self.width == thumbnail.width
                and self.height == thumbnail.height
            )
        )

        return same

    def as_dict(self) -> dict[str, str | int | UUID]:
        '''
        Returns a dict representation of the thumbnail
        '''

        data: dict[str, str | int | UUID] = {
            'thumbnail_id': self.thumbnail_id,
            'url': self.url,
            'width': self.width,
            'height': self.height,
            'preference': self.preference,
            'size': self.size,
        }

        if self.youtube_url:
            data['youtube_url'] = self.youtube_url

        if self.display_hint:
            data['display_hint'] = self.display_hint

        return data

    async def ingest(self, video_id: UUID, storage_driver: FileStorage, member: Member,
                     work_dir: str) -> str:
        '''
        Downloads the thumbnail to the local file system and saves it to
        (cloud) storage. This function does not delete the temporary file
        it creates in the working directory

        :param video_id: the UUID of the video in the personal data store
        :param storage_driver: the storage driver to persist the thumbnail to
        :param member: the member to which the video belongs
        :param work_dir: the directory to store the thumbnail temporarily in
        :returns: the URL of the thumbnail in storage
        '''

        _LOGGER.debug(f'Downloading thumbnail {self.url}')

        self.youtube_url = self.url

        try:
            parsed_url: ParseResult = urlparse(self.url)
            filename: str = os.path.basename(parsed_url.path)
            with open(f'{work_dir}/{filename}', 'wb') as file_desc:
                async with AsyncHttpClient() as client:
                    async with client.stream('GET', self.url) as resp:
                        content_type: str = resp.headers.get('content-type')
                        async for chunk in resp.aiter_bytes():
                            file_desc.write(chunk)
        except Exception as exc:
            _LOGGER.debug(f'Failed to download thumbnail {self.url}: {exc}')
            raise ByodaRuntimeError('Thumbnail download failure') from exc

        ext: str | None = None
        _, ext = os.path.splitext(filename)
        if not ext or ext not in ['.png', '.jpg', '.jpeg', 'webp']:
            ext = ContentTypesByType.get(content_type)

        try:
            with open(f'{work_dir}/{filename}', 'rb') as file_desc:
                filepath: str = f'{video_id}/{filename}'
                if ext:
                    filepath += ext

                _LOGGER.debug(f'Copying thumbnail to storage: {filepath}')
                await storage_driver.write(
                    filepath, file_descriptor=file_desc,
                    storage_type=StorageType.PUBLIC
                )
        except Exception as exc:
            _LOGGER.debug(f'Failed to save thumbnail to storage {exc}')
            raise ByodaRuntimeError('Save thumbnail failure') from exc

        self.url: str = Paths.PUBLIC_THUMBNAIL_CDN_URL.format(
            service_id=member.service_id, member_id=member.member_id,
            asset_id=video_id, filename=filename, ext=ext
        )

        _LOGGER.debug(f'New URL for thumbnail: {self.url}')
        return self.url
