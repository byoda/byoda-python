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
import json
from enum import Enum
from typing import Dict, List

from byoda.secrets import DataSecret

from byoda.datatypes import CloudType
from byoda.storage import FileStorage, FileMode

_LOGGER = logging.getLogger(__name__)


class DocumentStoreType(Enum):
    OBJECT_STORE        = "objectstore"     # noqa=E221


class DocumentStore:
    def __init__(self):
        self.backend: FileStorage = None
        self.store_type: DocumentStoreType = None

    @staticmethod
    def get_document_store(storage_type: DocumentStoreType,
                           cloud_type: CloudType.AWS = CloudType,
                           bucket_prefix: str = None, root_dir: str = None
                           ):
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
            storage.backend = FileStorage.get_storage(
                cloud_type, bucket_prefix, root_dir
            )
        else:
            raise ValueError(f'Unsupported storage type: {storage_type}')

        return storage

    async def read(self, filepath: str, data_secret: DataSecret) -> Dict:
        '''
        Reads, decrypts and deserializes a JSON document
        '''

        # DocumentStore only stores encrypted data, which is binary
        data = await self.backend.read(filepath, file_mode=FileMode.BINARY)

        if data_secret:
            data = data_secret.decrypt(data)

        if data:
            data = json.loads(data)
        else:
            data = dict()

        return data

    async def write(self, filepath: str, data: Dict, data_secret: DataSecret):
        '''
        Encrypts the data, serializes it to JSON and writes the data to storage
        '''

        data = json.dumps(data, indent=4, sort_keys=True)

        data = data_secret.encrypt(data)

        await self.backend.write(filepath, data, file_mode=FileMode.BINARY)

    async def get_folders(self, folder_path: str, prefix: str = None
                          ) -> List[str]:
        '''
        Get the sub-directories in a directory. With some storage backends,
        this functionality will be emulated as it doesn't support directories
        or folders.
        '''

        return await self.backend.get_folders(folder_path, prefix)
