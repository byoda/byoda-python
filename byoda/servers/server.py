'''
Class for modeling the different server types, ie.:
POD server, directory server, service server

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

from typing import TypeVar
from datetime import datetime

from byoda.util.paths import Paths

from byoda.datatypes import ServerType
from byoda.datatypes import CloudType

from byoda.datastore.document_store import DocumentStoreType, DocumentStore


_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')
Account = TypeVar('Account')
Service = TypeVar('Service')
RegistrationStatus = TypeVar('RegistrationStatus')


class Server:
    def __init__(self, network: Network):
        self.server_type: ServerType = None
        self.network: Network = network
        self.account: Account = None
        self.service: Service = None
        self.document_store: DocumentStore = None
        self.cloud = None
        self.paths: Paths = None
        self.started: datetime = datetime.utcnow()

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
