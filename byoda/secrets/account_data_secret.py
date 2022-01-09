'''
Cert manipulation for data of an account

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from uuid import UUID
from typing import TypeVar
from copy import copy

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType
from .data_secret import DataSecret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class AccountDataSecret(DataSecret):
    def __init__(self, account: str = 'pod', account_id: UUID = None,
                 network: Network = None):
        '''
        Class for the account-data secret. This secret is used to encrypt
        account data and to sign documents

        :raises: (none)
        '''

        self.account_id = account_id
        if account_id and not isinstance(account_id, UUID):
            self.account_id = UUID(account_id)

        self.paths = copy(network.paths)
        self.account = str(account)
        self.paths.account = self.account
        self.paths.account_id = self.account_id

        super().__init__(
            cert_file=self.paths.get(Paths.ACCOUNT_DATA_CERT_FILE),
            key_file=self.paths.get(Paths.ACCOUNT_DATA_KEY_FILE),
            storage_driver=self.paths.storage_driver
        )
        self.account = self.paths.account
        self.network = network
        self.id_type = IdType.ACCOUNT_DATA

    def create_csr(self, account_id: UUID = None) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param service_id: identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        if account_id:
            self.account_id = account_id

        if not self.network:
            raise ValueError('Network not defined')

        # TODO: SECURITY: add constraints
        common_name = (
            f'{self.account_id}.{self.id_type.value}.{self.network.name}'
        )

        return super().create_csr(common_name, key_size=4096, ca=self.ca)
