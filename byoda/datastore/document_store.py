'''
Class for certificate request processing

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
import json
from enum import Enum
from typing import Dict, List

from byoda.datatypes import CloudType
from byoda.storage import FileStorage

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
        Factory for initating a document store
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

    def read(self, filepath) -> Dict:
        '''
        Reads and deserializes a JSON document
        '''

        data = self.backend.read(filepath)
        if data:
            return json.loads(data)
        else:
            return {}

    def write(self, filepath: str, data: Dict):
        '''
        Serializes to JSON and writes data to storage
        '''

        self.backend.write(filepath, data)

    def get_folders(self, folder_path: str, prefix: str = None) -> List[str]:
        return self.backend.get_folders(folder_path, prefix)
