'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from copy import copy
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger
from datetime import datetime
from datetime import timedelta

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType
from byoda.datatypes import TEMP_SSL_DIR

from .secret import Secret

_LOGGER: Logger = getLogger(__name__)

Network = TypeVar('Network')


class AccountSecret(Secret):
    '''
    The account secret is used as TLS secret on the Account API endpoint
    of the pod
    '''

    __slots__ = ['account_id', 'account', 'network', 'paths_account_id']
    # When should the secret be renewed
    RENEW_WANTED: datetime = datetime.now() + timedelta(days=180)
    RENEW_NEEDED: datetime = datetime.now() + timedelta(days=30)

    def __init__(self, account: str = 'pod', account_id: UUID = None,
                 network: Network = None):
        '''
        Class for the network Account secret

        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.account_id: UUID | str = account_id
        if account_id and not isinstance(account_id, UUID):
            self.account_id = UUID(account_id)

        self.paths: Paths = copy(network.paths)
        self.account: str = str(account)
        self.paths.account: str = self.account
        self.paths_account_id: UUID = self.account_id

        super().__init__(
            cert_file=self.paths.get(Paths.ACCOUNT_CERT_FILE),
            key_file=self.paths.get(Paths.ACCOUNT_KEY_FILE),
            storage_driver=self.paths.storage_driver
        )

        self.account: str = self.paths.account
        self.network: Network = network
        self.id_type: IdType = IdType.ACCOUNT

    async def create_csr(self, account_id: UUID = None, renew: bool = False
                         ) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param account_id: identifier for the account to be used in the CSR
        :param renew: should any existing private key be used to
        renew an existing certificate
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

        return await super().create_csr(common_name, ca=self.ca, renew=renew)

    @staticmethod
    def create_commonname(account_id: UUID, network: str):
        '''
        Returns the FQDN to use in the common name for the secret
        '''

        if not isinstance(account_id, UUID):
            account_id = UUID(account_id)

        if not isinstance(network, str):
            raise TypeError(
                f'Network parameter must be a string, not a {type(network)}'
            )

        fqdn = f'{account_id}.{IdType.ACCOUNT.value}.{network}'

        return fqdn

    def save_tmp_private_key(self) -> str:
        '''
        Save the private key for the AccountSecret so angie and the python
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

        return f'{TEMP_SSL_DIR}/{self.account_id}/private-account.key'
