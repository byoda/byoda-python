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
from urllib.parse import urlparse, ParseResult

from aiohttp import ClientSession as HttpClientSession

from byoda.datamodel.member import Member

from byoda.storage.filestorage import FileStorage

from byoda.datatypes import StorageType

from byoda.util.paths import Paths

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
            'thumbnail_id': self.thumbnail_id,
            'url': self.url,
            'width': self.width,
            'height': self.height,
            'preference': self.preference,
            'size': self.size
        }

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
        '''

        _LOGGER.debug(f'Downloading thumbnail {self.url}')

        parsed_url: ParseResult = urlparse(self.url)
        filename: str = os.path.basename(parsed_url.path)
        with open(f'{work_dir}/{filename}', 'wb') as file_desc:
            async with HttpClientSession() as session:
                async with session.get(self.url) as response:
                    async for chunk in response.content.iter_chunked(
                            CHUNK_SIZE):
                        file_desc.write(chunk)

        with open(f'{work_dir}/{filename}', 'rb') as file_desc:
            filepath: str = f'{video_id}/{filename}'
            _LOGGER.debug(f'Copying thumbnail to storage: {filepath}')
            await storage_driver.write(
                filepath, file_descriptor=file_desc,
                storage_type=StorageType.PUBLIC
            )

        self.url: str = Paths.PUBLIC_THUMBNAIL_CDN_URL.format(
            service_id=member.service_id, member_id=member.member_id,
            asset_id=video_id, filename=filename
        )

        _LOGGER.debug(f'New URL for thumbnail: {self.url}')
        return self.url
