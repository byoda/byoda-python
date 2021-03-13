'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID
from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType

from . import Secret

_LOGGER = logging.getLogger(__name__)


class AccountSecret(Secret):
    def __init__(self, paths: Paths):
        '''
        Class for the network Account secret

        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        super().__init__(
            cert_file=paths.get(Paths.ACCOUNT_CERT_FILE),
            key_file=paths.get(Paths.ACCOUNT_KEY_FILE),
        )

        self.account_id = None
        self.account_alias = paths.account
        self.network = paths.network
        self.ca = False
        self.id_type = IdType.ACCOUNT

    def create(self):
        raise NotImplementedError

    def create_csr(self, account_id: UUID) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param account_id: account_id
        :returns: csr
        :raises: ValueError if the Secret instance already has a private key
        or cert
        '''

        self.account_id = account_id
        common_name = f'{self.account_id}.{self.id_type.value}.{self.network}'

        return super().create_csr(common_name, ca=self.ca)

    def review_csr(self):
        raise NotImplementedError

    def review_commonname(self, commonname: str) -> UUID:
        '''
        Checks if the structure of common name matches with a common name of
        an AccountSecret. If so, it sets the 'account_id' property of the
        instance to the UUID parsed from the commonname

        :param commonname: the commonname to check
        :returns: account uuid
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        commonname_prefix = super().review_commonname(commonname)

        bits = commonname_prefix.split('.')
        if len(bits) > 2:
            raise ValueError(f'Invalid number of domain levels: {commonname}')

        user_id, subdomain = bits[0:1]
        if subdomain != 'accounts':
            raise ValueError(f'commonname {commonname} is not for an account')

        try:
            uuid = UUID(user_id)
        except ValueError:
            raise ValueError(f'{user_id} is not a valid UUID')

        self.account_id = uuid

        return uuid
