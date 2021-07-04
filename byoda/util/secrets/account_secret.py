'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID
from typing import TypeVar
from copy import copy

from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType
from . import Secret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class AccountSecret(Secret):
    def __init__(self, account: str = 'pod', account_id: UUID = None,
                 network: Network = None):
        '''
        Class for the network Account secret

        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.account_id = account_id
        if account_id and not isinstance(account_id, UUID):
            self.account_id = UUID(account_id)

        self.paths = copy(network.paths)
        self.account = str(account)
        self.paths.account = self.account
        self.paths_account_id = self.account_id

        super().__init__(
            cert_file=self.paths.get(Paths.ACCOUNT_CERT_FILE),
            key_file=self.paths.get(Paths.ACCOUNT_KEY_FILE),
            storage_driver=self.paths.storage_driver
        )

        self.account = self.paths.account
        self.network = network
        self.id_type = IdType.ACCOUNT

    def create_csr(self, account_id: UUID = None) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param account_id: account_id
        :returns: csr
        :raises: ValueError if the Secret instance already has a private key
        or cert
        '''

        if account_id:
            self.account_id = account_id

        if not self.network:
            raise ValueError('Network not defined')

        common_name = f'{self.account_id}.{self.id_type.value}.{self.network.network}'

        return super().create_csr(common_name, ca=self.ca)
