'''
Class for modeling the different server types, ie.:
POD server, directory server, service server

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from enum import Enum
from typing import TypeVar


from byoda.util import Paths

from byoda.datatypes import CloudType

from byoda.datastore import DocumentStoreType, DocumentStore


_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')
Account = TypeVar('Account')
Service = TypeVar('Service')
RegistrationStatus = TypeVar('RegistrationStatus')


class ServerType(Enum):
    Pod         = 'pod'             # noqa: E221
    Directory   = 'directory'       # noqa: E221
    Service     = 'service'         # noqa: E221


class Server:
    def __init__(self):
        self.server_type: ServerType = None
        self.network: Network = None
        self.account: Account = None
        self.service: Service = None
        self.document_store: DocumentStore = None
        self.cloud = None
        self.paths: Paths = None

    def load_secrets(self, password: str = None):
        '''
        Loads the secrets of the server
        '''
        raise NotImplementedError

    def set_document_store(self, store_type: DocumentStoreType,
                           cloud_type: CloudType = None,
                           bucket_prefix: str = None, root_dir: str = None
                           ) -> None:

        self.cloud = cloud_type

        self.document_store = DocumentStore.get_document_store(
            store_type, cloud_type=cloud_type, bucket_prefix=bucket_prefix,
            root_dir=root_dir
        )
