'''
Cert manipulation for apps

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from copy import copy
from typing import TypeVar
from logging import getLogger

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType
from byoda.datatypes import TEMP_SSL_DIR

from byoda.util.logger import Logger

from .secret import Secret

_LOGGER: Logger = getLogger(__name__)

Account = TypeVar('Account')
Service = TypeVar('Service')
Network = TypeVar('Network')


class AppSecret(Secret):
    __slots__ = ['app_id', 'service_id', 'network', 'fqdn']

    def __init__(self, app_id: UUID, service_id: int, network: Network):
        '''
        Class for the App secret for a service

        :param app_id: the UUID for the App
        :param service_id: the service id
        '''

        self.app_id: UUID = app_id
        service_id = int(service_id)

        self.fqdn: str | None = None

        self.paths: Paths = copy(network.paths)
        self.paths.service_id: int = service_id

        super().__init__(
            cert_file=self.paths.get(Paths.APP_CERT_FILE, app_id=self.app_id),
            key_file=self.paths.get(Paths.APP_KEY_FILE, app_id=self.app_id),
            storage_driver=self.paths.storage_driver
        )

        self.service_id: int = service_id
        self.network: str = network.name
        self.id_type: IdType = IdType.APP

    async def create_csr(self, fqdn: str, renew: bool = False
                         ) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param app_id: identifier of the app for the service
        :param renew: if True, renew the secret using the existing private key
        :returns: csr
        :raises: ValueError if the Secret instance already has
        a private key or cert
        '''

        self.fqdn: str = fqdn

        # TODO: SECURITY: add constraints
        common_name: str = AppSecret.create_commonname(
            self.app_id, self.service_id, self.network
        )
        return await super().create_csr(
            common_name, sans=[self.fqdn], key_size=4096, ca=self.ca,
            renew=renew
        )

    @staticmethod
    def create_commonname(app_id: UUID, service_id: int, network: str):
        '''
        generates the FQDN for the common name in the app TLS secret
        '''

        if not isinstance(app_id, UUID):
            app_id = UUID(app_id)

        service_id = int(service_id)

        if not isinstance(network, str):
            raise TypeError(
                f'Network parameter must be a string, not a {type(network)}'
            )

        common_name = (
            f'{app_id}.{IdType.APP.value}{service_id}.{network}'
        )

        return common_name

    async def load(self, with_private_key: bool = True,
                   password: str = 'byoda'):
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

    def save_tmp_private_key(self):
        '''
        Save the private key for the AppSecret so nginx and the python
        requests module can use it.
        '''
        return super().save_tmp_private_key(
            filepath=self.get_tmp_private_key_filepath()
        )

    def get_tmp_private_key_filepath(self) -> str:
        '''
        Gets the location where on local storage the unprotected private
        key is stored
        '''

        return f'{TEMP_SSL_DIR}/private-app-{self.app_id}.key'
