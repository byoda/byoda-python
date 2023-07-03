'''
Model a thumbnail of a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import logging

from enum import Enum
from uuid import uuid4
from uuid import UUID
from tempfile import SpooledTemporaryFile
from urllib.parse import urlparse, ParseResult

import orjson

from aiohttp import ClientSession as HttpClientSession

from byoda.datatypes import StorageType

from byoda.storage.filestorage import FileStorage

_LOGGER = logging.getLogger(__name__)

MAX_SPOOLED_FILE: int = 1024 * 1024
CHUNK_SIZE: int = 64 * 1024

class YouTubeThumbnailSize(Enum):
    # flake8: noqa=E221
    DEFAULT         = 'default'
    MEDIUM          = 'medium'
    HIGH            = 'high'


class YouTubeThumbnail:
    def __init__(self, size: str, data: dict):
        self.thumbnail_id: UUID = uuid4()
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

    async def ingest(self, video_id: UUID, storage_driver: FileStorage) -> str:
        '''
        Downloads the thumbnail to the local file system
        '''

        _LOGGER.debug(f'Downloading thumbnail {self.url}')

        with SpooledTemporaryFile(max_size=MAX_SPOOLED_FILE) as file_desc:
            async with HttpClientSession() as session:
                async with session.get(self.url) as response:
                    async for chunk in response.content.iter_chunked(
                            CHUNK_SIZE):
                        file_desc.write(chunk)

            file_desc.seek(0)

            parsed_url: ParseResult = urlparse(self.url)
            filename = os.path.basename(parsed_url.path)
            filepath = f'{video_id}/{filename}'

            _LOGGER.debug(f'Copying thumbnail to storage: {filepath}')
            await storage_driver.write(
                filepath, file_descriptor=file_desc,
                storage_type=StorageType.PUBLIC
            )

            self.url = storage_driver.get_url(
                filepath, storage_type=StorageType.PUBLIC
            )

            _LOGGER.debug(f'New URL for thumbnail: {self.url}')
            return self.url
