'''
The document store handles storing various files of a pod, such as
certificates, keys, and service contracts.

The DocumentStore can be extended to support different backend storage. It
currently only supports local file systems and object storage of Azure, AWS,
and GCP.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from enum import Enum
from typing import TypeVar
from logging import Logger
from logging import getLogger


import orjson

from byoda.datamodel.datafilter import DataFilterSet

from byoda.secrets.data_secret import DataSecret

from byoda.datatypes import CloudType
from byoda.storage.filestorage import FileStorage, FileMode
from byoda.storage.sqlite import SqliteStorage

Member = TypeVar('Member')

_LOGGER: Logger = getLogger(__name__)


class DocumentStoreType(Enum):
    OBJECT_STORE        = 'objectstore'     # noqa=E221


class DocumentStore:
    def __init__(self):
        self.backend: FileStorage | SqliteStorage | None = None
        self.store_type: DocumentStoreType | None = None

    @staticmethod
    async def get_document_store(storage_type: DocumentStoreType,
                                 cloud_type: CloudType = None,
                                 private_bucket: str = None,
                                 restricted_bucket: str = None,
                                 public_bucket: str = None,
                                 root_dir: str = None):
        '''
        Factory for initiating a document store
        '''

        storage = DocumentStore()
        if storage_type == DocumentStoreType.OBJECT_STORE:
            if not (cloud_type and private_bucket and restricted_bucket and
                    public_bucket):
                raise ValueError(
                    f'Must specify cloud_type and public/restricted/private '
                    f'buckets for document storage {storage_type}'
                )
            storage.backend = await FileStorage.get_storage(
                cloud_type, private_bucket, restricted_bucket, public_bucket,
                root_dir
            )
        else:
            raise ValueError(f'Unsupported storage type: {storage_type}')

        return storage

    async def read(self, member: Member = None, class_name: str = None,
                   filepath: str = None, data_secret: DataSecret = None,
                   filters: DataFilterSet = None) -> dict:
        '''
        Reads data from the backend storage
        '''

        if (member or class_name or filters) and (filepath or data_secret):
            raise ValueError(
                'Cannot specify both member, class_name, filters and '
                'filepath, data_secret'
            )

        # TODO: add methods to FileStorage and SqliteStorage classes so we do
        # not need to use isinstance() here
        if isinstance(self.backend, FileStorage):
            # DocumentStore only stores encrypted data, which is binary
            data: str = await self.backend.read(
                filepath, file_mode=FileMode.BINARY
            )

            if data_secret:
                data = data_secret.decrypt(data)

            _LOGGER.debug(f'Read {data.decode("utf-8")} from {filepath}')
            if data:
                data = orjson.loads(data)
            else:
                data = dict()
        elif isinstance(self.backend, SqliteStorage):
            data = await self.backend.read(member, class_name, filters)

        _LOGGER.debug(f'Read {len(data)} items')

        return data

    async def write(self, filepath: str, data: dict, data_secret: DataSecret):
        '''
        Encrypts the data, serializes it to JSON and writes the data to storage
        '''

        data = orjson.dumps(
            data, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2
        )

        _LOGGER.debug(f'Wrote {len(data)} items')

        encrypted_data = data_secret.encrypt(data)

        await self.backend.write(
            filepath, encrypted_data, file_mode=FileMode.BINARY
        )

    async def get_folders(self, folder_path: str, prefix: str = None
                          ) -> list[str]:
        '''
        Get the sub-directories in a directory. With some storage backends,
        this functionality will be emulated as it doesn't support directories
        or folders.
        '''

        return await self.backend.get_folders(folder_path, prefix)
