'''
Class for certificate request processing

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from enum import Enum

from ariadne import load_schema_from_path, make_executable_schema
from ariadne import QueryType

from byoda.datatypes import CloudType
from byoda.storage import FileStorage

_LOGGER = logging.getLogger(__name__)

query = QueryType()


@query.field('person')
def resolve_person(obj, info, given_name='none', family_name='none',
                   email='none'):
    return {
        'given_name': given_name,
        'family_name': family_name,
        'email': email,
    }


class MemberQuery():
    '''
    Queries and mutations for membership data
    '''
    def __init__(self, directory):
        # load_schema_from_path uses ariadne.gql so no need to explicitly
        # use it.
        self.type_defs = load_schema_from_path(directory)
        global query
        self.schema = make_executable_schema(self.type_defs, query)


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
