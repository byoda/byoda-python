'''
Cert manipulation signing data by an app

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''


from uuid import UUID
from copy import copy
from typing import TypeVar
from typing import override
from logging import Logger
from logging import getLogger

from cryptography.x509 import Certificate
from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType

from byoda.servers.server import Server

from byoda import config

from .data_secret import DataSecret

_LOGGER: Logger = getLogger(__name__)

Network = TypeVar('Network')


class AppDataSecret(DataSecret):
    __slots__: list[str] = ['app_id', 'service_id', 'network', 'fqdn', 'paths']

    @override
    def __init__(self, app_id: UUID, service_id: int,
                 network: Network | None = None) -> None:
        '''
        Class for the app-data secret. This secret is used to sign
        data such as claims

        :param app_id: identifier for the app
        :param service_id: identifier for the service
        :param network: network instance
        :returns: (none)
        :raises: (none)
        '''

        server: Server = config.server

        if not network:
            network = server.network

        self.app_id: UUID = app_id
        service_id = int(service_id)

        self.fqdn: str | None = None

        self.paths: Paths = copy(network.paths)
        self.paths.service_id = service_id

        super().__init__(
            cert_file=self.paths.get(Paths.APP_DATA_CERT_FILE, app_id=app_id),
            key_file=self.paths.get(Paths.APP_DATA_KEY_FILE, app_id=app_id),
            storage_driver=self.paths.storage_driver
        )

        self.service_id: int = service_id
        self.network: str = network.name
        self.id_type: IdType = IdType.APP_DATA

    @override
    async def load(self, with_private_key: bool = True,
                   password: str = 'byoda') -> None:
        await super().load(
            with_private_key=with_private_key, password=password
        )
        if self.app_id:
            common_name_app_id: UUID = UUID(self.common_name.split('.')[0])
            if self.app_id != common_name_app_id:
                raise ValueError(
                    f'The app_id {self.app_id} does not match the common '
                    f'name in the certificate: {common_name_app_id}'
                )
        else:
            self.app_id = UUID(self.common_name.split('.')[0])

    @override
    async def create_csr(self, fqdn: str, renew: bool = False
                         ) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param app_id: identifier for the app
        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: csr
        :raises: ValueError if the Secret instance already has
        a private key or cert
        '''

        self.fqdn: str = fqdn


        common_name: str = AppDataSecret.create_commonname(
            self.app_id, self.service_id, self.network
        )

        return await super().create_csr(
            common_name, sans=[self.fqdn], renew=renew
        )

    @staticmethod
    @override
    def create_commonname(app_id: UUID, service_id: int, network: str) -> str:
        '''
        generates the FQDN for the common name in the app TLS secret
        '''

        if not isinstance(app_id, UUID):
            app_id = UUID(app_id)

        service_id = int(service_id)

        if not isinstance(network, str):
            raise TypeError(
                f'Network parameter must be a string, not type {type(network)}'
            )

        common_name: str = (
            f'{app_id}.{IdType.APP_DATA.value}{service_id}.{network}'
        )

        return common_name

    @override
    async def download(self, fingerprint: str | None = None) -> str | None:
        '''
        Downloads the app-data secret from the network

        :param app_id: the app_id for the app
        :param fingerprint: the fingerprint of the certificate
        returns: (none)
        :raises: (none)
        '''

        url: str = self.paths.get(
            Paths.APP_DATACERT_DOWNLOAD, app_id=self.app_id
        )

        return await super().download(url, fingerprint=fingerprint)

    async def download_cert(self, fingerprint: str | None = None) -> None:
        '''
        Downloads the app-data secret from the network

        :param app_id: the app_id for the app
        :param fingerprint: the fingerprint of the certificate
        returns: (none)
        :raises: (none)
        '''

        log_data: dict[str, any] = {
            'fingerprint': fingerprint,
            'app_id': self.app_id,
            'id_type': self.id_type,
        }
        cert_cache: dict[str, dict[IdType, Certificate]] = config.data_certs
        if (fingerprint in cert_cache
                and self.id_type in cert_cache[fingerprint]):
            self.cert = cert_cache[fingerprint][self.id_type]
            _LOGGER.debug('Got data cert from cache', extra=log_data)
            return

        url: str = self.paths.get(
            Paths.APP_DATACERT_DOWNLOAD, app_id=self.app_id
        )
        log_data['url'] = url
        cert_data: str | None = await super().download(
            url, fingerprint=fingerprint
        )
        self.from_string(cert_data)

        if fingerprint not in cert_cache:
            cert_cache[fingerprint] = {}

        _LOGGER.debug('Adding data cert to cache', extra=log_data)
        cert_cache[fingerprint][self.id_type] = self.cert
