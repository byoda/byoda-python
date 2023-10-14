'''
Class for modeling app on a social network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''


from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service

from byoda.secrets.app_secret import AppSecret
from byoda.secrets.app_data_secret import AppDataSecret
from byoda.storage.filestorage import FileStorage

_LOGGER: Logger = getLogger(__name__)


class App:
    def __init__(self, app_id: UUID, service: Service,
                 storage_driver: FileStorage = None):
        self.app_id: UUID = app_id
        self.service: Service = service
        self.network: Network = service.network
        if storage_driver:
            self.storage_driver: FileStorage = storage_driver
        else:
            self.storage_driver: FileStorage = \
                self.network.paths.storage_driver

        _LOGGER.debug(
            f'Instantiated App for service ID: {self.service.service_id}'
        )

    async def load_secrets(self, with_private_key: bool = True,
                           password: str = None):
        '''
        Loads the secrets for the app from the local storage or from the cloud
        '''

        self.tls_secret = AppSecret(
            self.app_id, service_id=self.service.service_id,
            network=self.network
        )
        await self.tls_secret.load(
            with_private_key=with_private_key, password=password
        )

        self.data_secret = AppDataSecret(
            self.app_id, service_id=self.service.service_id,
            network=self.network
        )
        await self.data_secret.load(
            with_private_key=with_private_key, password=password
        )
