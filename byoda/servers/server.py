'''
Class for modeling the different server types, ie.:
POD server, directory server, service server

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''


from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger
from datetime import datetime
from datetime import timezone

from byoda.util.paths import Paths

from byoda.datatypes import ServerType
from byoda.datatypes import CloudType

from byoda.datastore.document_store import DocumentStoreType, DocumentStore
from byoda.datastore.data_store import DataStore
from byoda.storage.filestorage import FileStorage

from byoda.util.api_client.api_client import ApiClient

_LOGGER: Logger = getLogger(__name__)

Network = TypeVar('Network')
Account = TypeVar('Account')
Service = TypeVar('Service')
RegistrationStatus = TypeVar('RegistrationStatus')
JWT = TypeVar('JWT')


class Server:
    def __init__(self, network: Network,
                 cloud_type: CloudType = CloudType.LOCAL) -> None:

        self.server_type: ServerType | None = None
        self.cloud: CloudType = cloud_type

        self.network: Network = network
        self.account: Account | None = None
        self.service: Service | None = None

        self.document_store: DocumentStore | None = None
        self.data_store: DataStore | None = None

        self.storage_driver: FileStorage | None = None
        self.local_storage: FileStorage | None = None
        self.paths: Paths | None = None

        self.started: datetime = datetime.now(timezone.utc)

        # If we are bootstrapping and there are no secrets
        # or account DB files on the local storage or in the
        # cloud then we will create new ones
        self.bootstrapping: bool = False

        # The POD will get its own TLS certificate and private key
        # for this custom domain so people can connect to it with
        # their browsers
        self.custom_domain: str | None = None

        # The POD will manage the angie process if it is not running
        # on a shared webserver
        self.shared_webserver: bool = False

    async def load_secrets(self, password: str = None) -> None:
        '''
        Loads the secrets of the server
        '''
        raise NotImplementedError

    async def set_document_store(self, store_type: DocumentStoreType,
                                 cloud_type: CloudType = None,
                                 private_bucket: str = None,
                                 restricted_bucket: str = None,
                                 public_bucket: str = None,
                                 root_dir: str = None) -> None:

        self.cloud = cloud_type

        _LOGGER.debug(
            f'Setting document store to {store_type} on cloud {cloud_type}'
        )
        self.document_store = await DocumentStore.get_document_store(
            store_type, cloud_type=cloud_type, private_bucket=private_bucket,
            restricted_bucket=restricted_bucket, public_bucket=public_bucket,
            root_dir=root_dir
        )

        self.storage_driver: FileStorage = self.document_store.backend

        self.local_storage: FileStorage = None

    async def review_jwt(self, jwt: JWT) -> None:
        raise NotImplementedError

    async def get_jwt_secret(self, jwt: JWT) -> None:
        raise NotImplementedError

    def accepts_jwts(self) -> None:
        raise NotImplementedError

    async def shutdown(self) -> None:
        '''
        Shuts down the server
        '''

        await ApiClient.close_all()
