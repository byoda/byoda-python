'''
Cert manipulation signing data by an app

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from uuid import UUID
from copy import copy
from typing import TypeVar

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType
from .data_secret import DataSecret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')


class AppDataSecret(DataSecret):
    def __init__(self, service_id: int, network: Network, fqdn: str):
        '''
        Class for the app-data secret. This secret is used to sign
        data such as claims

        :param service_id: identifier for the service
        :param network: network instance
        :param fqdn: the FQDN of the website for the app
        :raises: (none)
        '''

        self.paths: Paths = copy(network.paths)
        self.paths.service_id: int = int(service_id)

        super().__init__(
            cert_file=self.paths.get(Paths.APP_DATA_CERTCHAIN_FILE, fqdn=fqdn),
            key_file=self.paths.get(Paths.APP_DATA_KEY_FILE, fqdn=fqdn),
            storage_driver=self.paths.storage_driver
        )

        self.service_id: int = int(service_id)
        self.network: str = self.paths.network
        self.id_type: IdType = IdType.APP_DATA
        self.fqdn: str = fqdn

    async def create_csr(self, app_id: UUID, renew: bool = False
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

        self.app_id: UUID = app_id
        # TODO: SECURITY: add constraints
        common_name = (
            f'{app_id}.{self.id_type.value}{self.service_id}.{self.network}'
        )

        return await super().create_csr(
            common_name, sans=[self.fqdn], key_size=4096, ca=self.ca,
            renew=renew
        )
