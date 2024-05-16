'''
Class for modeling app on a social network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023, 2024
:license    : GPLv3
'''


from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service

from byoda.datatypes import IdType
from byoda.datatypes import AppType

from byoda.requestauth.jwt import JWT

from byoda.secrets.app_secret import AppSecret
from byoda.secrets.app_data_secret import AppDataSecret
from byoda.storage.filestorage import FileStorage

_LOGGER: Logger = getLogger(__name__)


class App:
    def __init__(self, app_id: UUID, service: Service,
                 storage_driver: FileStorage = None) -> None:
        self.app_id: UUID = app_id
        self.service: Service = service
        self.service_id: int = service.service_id
        self.network: Network = service.network
        self.app_type: AppType | None = None

        if storage_driver:
            self.storage_driver: FileStorage = storage_driver
        else:
            self.storage_driver: FileStorage = \
                self.network.paths.storage_driver

        _LOGGER.debug(
            f'Instantiated App for service ID: {self.service.service_id}'
        )

    async def load_secrets(self, with_private_key: bool = True,
                           password: str = None) -> None:
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


class CdnApp(App):
    def __init__(self, app_id: UUID, service: Service, cdn_origin_site_id: str
                 ) -> None:
        super().__init__(app_id, service)

        self.app_type = AppType.CDN

        if not cdn_origin_site_id or not isinstance(cdn_origin_site_id, str):
            raise ValueError('cdn_origin_site_id string is required')

        self.cdn_origin_site_id: str = cdn_origin_site_id


class PayApp(App):
    def __init__(self, app_id: UUID, service: Service, pay_url: str
                 ) -> None:
        super().__init__(app_id, service)

        self.app_type = AppType.PAYMENT

        if not pay_url or not isinstance(pay_url, str):
            raise ValueError('pay_rl string is required')

        self.pay_url: str = pay_url
