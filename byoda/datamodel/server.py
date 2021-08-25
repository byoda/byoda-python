'''
Class for modeling the different server types, ie.:
POD server, directory server, service server

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from enum import Enum

from byoda import config

from byoda.datatypes import CloudType

from byoda.datastore import DocumentStoreType, DocumentStore


_LOGGER = logging.getLogger(__name__)


class ServerType(Enum):
    POD         = 'pod'             # noqa: E221
    DIRECTORY   = 'directory'       # noqa: E221
    SERVICE     = 'service'         # noqa: E221


class Server:
    def __init__(self):
        self.server_type = None
        self.network = None
        self.account = None
        self.document_store = None
        self.cloud = None

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


class PodServer(Server):
    def __init__(self):
        super().__init__()

        self.server_type = ServerType.POD

    def load_secrets(self, password: str = None):
        '''
        Loads the secrets used by the podserver
        '''
        self.account.load_secrets(password)

        # We use the account secret as client TLS cert for outbound
        # requests and as private key for the TLS server
        filepath = self.account.tls_secret.save_tmp_private_key()

        config.requests.cert = (
            self.account.tls_secret.cert_file, filepath
        )


class DirectoryServer(Server):
    def __init__(self):
        super().__init__()

        self.server_type = ServerType.DIRECTORY

    def load_secrets(self, connection: str = None):
        '''
        Loads the secrets used by the directory server
        '''
        self.network.load_secrets()

