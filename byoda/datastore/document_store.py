'''
Class for certificate request processing

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from enum import Enum



from byoda.datatypes import CloudType
from byoda.storage import FileStorage


_LOGGER = logging.getLogger(__name__)


class MemberQuery(ObjectType):
    hello = String(name=String(default_value='stranger'))
    goodbye = String()
    serviceid = Int(serviceid=Int(default_value=0))

    def resolve_hello(root, info, name):
        return f'Hello {name}!'

    def resolve_goodbye(root, info):
        return 'See ya!'

    def resolve_serviceid(self, info, serviceid):
        return serviceid


class DocumentStoreType(Enum):
    OBJECT_STORE        = "objectstore"     # noqa=E221


class DocumentStore:
    def __init__(self):
        self.backend = None
        self.store_type = None

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
