'''
Cert manipulation for accounts and members

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

        # TODO: SECURITY: add constraints
        if not self.network:
            raise ValueError('Network not defined')

        common_name = AccountSecret.create_commonname(
            self.account_id, self.network.name
        )

        return super().create_csr(common_name, ca=self.ca)

    @staticmethod
    def create_commonname(account_id: UUID, network: str):
        '''
        Returns the FQDN to use in the common name for the secret
        '''

        if not isinstance(account_id, UUID):
            account_id = UUID(account_id)

        if not isinstance(network, str):
            raise ('Network parameter must be a string')

        fqdn = f'{account_id}.{IdType.ACCOUNT.value}.{network}'

        return fqdn

    def save_tmp_private_key(self):
        '''
        Save the private key for the AccountSecret so nginx and the python
        requests module can use it.
        '''
        return super().save_tmp_private_key(
            filepath='/tmp/private-account.key'
        )
