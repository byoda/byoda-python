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
            storage_driver=paths.storage_driver
        )

        self.account_id = None
        self.account = paths.account
        self.network = paths.network
        self.ca = False
        self.id_type = IdType.ACCOUNT

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
