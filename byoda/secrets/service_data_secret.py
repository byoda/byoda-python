'''
Cert manipulation for data of an account

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import TypeVar
from copy import copy

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType
from .data_secret import DataSecret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')


class ServiceDataSecret(DataSecret):
    def __init__(self, service: str, service_id: int, network: Network):
        '''
        Class for the account-data secret. This secret is used to encrypt
        account data.
        :raises: (none)
        '''

        self.paths: Paths = copy(network.paths)
        self.paths.service_id: int = int(service_id)

        super().__init__(
            cert_file=self.paths.get(Paths.SERVICE_DATA_CERT_FILE),
            key_file=self.paths.get(Paths.SERVICE_DATA_KEY_FILE),
            storage_driver=self.paths.storage_driver
        )

        self.service: str = str(service)
        self.service_id: int = int(service_id)
        self.network: str = self.paths.network
        self.id_type: IdType = IdType.SERVICE_DATA

        self.accepted_csrs: dict[IdType, int] = ()

    async def create_csr(self, service_id: int = None, renew: bool = False
                         ) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param service_id: identifier for the service
        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        if service_id:
            self.service_id = int(service_id)

        # TODO: SECURITY: add constraints
        common_name = (
            f'data.{self.id_type.value}{self.service_id}.{self.network}'
        )

        return await super().create_csr(
            common_name, key_size=4096, ca=self.ca, renew=renew
        )
