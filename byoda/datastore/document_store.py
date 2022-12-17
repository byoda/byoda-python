'''
The document store handles storing the data of a pod for a service that
the pod is a member of. This data is stored as an encrypted JSON file.

The DocumentStore can be extended to support different backend storage. It
currently only supports local file systems and AWS S3. In the future it
can be extended by for NoSQL storage to improve scalability.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
import orjson
from enum import Enum

from byoda.datamodel.datafilter import DataFilterSet

from byoda.secrets import DataSecret

from byoda.datatypes import CloudType
from byoda.storage.filestorage import FileStorage, FileMode
from byoda.storage.sqlite import SqliteStorage

_LOGGER = logging.getLogger(__name__)


class DocumentStoreType(Enum):
    OBJECT_STORE        = 'objectstore'     # noqa=E221
    SQLITE              = 'sqlite'          # noqa=E221


class DocumentStore:
    def __init__(self):
        self.backend: FileStorage | SqliteStorage = None
        self.store_type: DocumentStoreType = None

    @staticmethod
    async def get_document_store(storage_type: DocumentStoreType,
                                 cloud_type: CloudType = None,
                                 bucket_prefix: str = None,
                                 root_dir: str = None):
        '''
        Factory for initiating a document store
        '''

        storage = DocumentStore()
        if storage_type == DocumentStoreType.OBJECT_STORE:
            if not (cloud_type and bucket_prefix):
                raise ValueError(
                    f'Must specify cloud_type and bucket_prefix for document '
                    f'storage {storage_type}'
                )
            storage.backend = await FileStorage.get_storage(
                cloud_type, bucket_prefix, root_dir
            )
        elif storage_type == DocumentStoreType.SQLITE:
            storage.backend = await SqliteStorage.setup()

        else:
            raise ValueError(f'Unsupported storage type: {storage_type}')

        return storage

    async def read(self, filepath: str, data_secret: DataSecret) -> dict:
        '''
        Reads, decrypts and deserializes a JSON document
        '''

        # DocumentStore only stores encrypted data, which is binary
        data = await self.backend.read(filepath, file_mode=FileMode.BINARY)

        if data_secret:
            data = data_secret.decrypt(data)

        _LOGGER.debug(f'Read {data.decode("utf-8")} from {filepath}')
        if data:
            data = orjson.loads(data)
        else:
            data = dict()

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

    async def query(self, key: str, filters: dict[str, dict]
                    ) -> dict[str, object]:

        return self.backend.query(key, filters)

    async def mutate(self, key: str, data: dict[str, object],
                     data_filter_set: DataFilterSet = None):
        return self.backend.mutate(key, data, data_filter_set)

    async def append(self, key: str, data: dict[str, object]):
        return self.backend.append(key, data)

    async def delete(self, key: str, data_filter_set: DataFilterSet = None):
        return self.backend.delete(key, data_filter_set)