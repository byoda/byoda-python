'''
Cert manipulation for data of an account

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
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

Account = TypeVar('Account', bound='Account')


class MemberDataSecret(DataSecret):
    def __init__(self, member_id: UUID, service_id: int, account: Account):
        '''
        Class for the member-data secret. This secret is used to encrypt
        data of an account for a service.
        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :returns: ValueError if both 'paths' and 'network' parameters are
        specified
        :raises: (none)
        '''

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)
        self.member_id = member_id

        self.service_id = int(service_id)

        self.paths = copy(account.paths)
        self.paths.service_id = self.service_id

        # secret.review_commonname requires self.network to be string
        self.network = account.network.name

        super().__init__(
            cert_file=self.paths.get(
                Paths.MEMBER_DATA_CERT_FILE,
                service_id=service_id, member_id=self.member_id,
            ),
            key_file=self.paths.get(
                Paths.MEMBER_DATA_KEY_FILE,
                service_id=service_id, member_id=self.member_id,
            ),
            storage_driver=self.paths.storage_driver
        )

        self.id_type = IdType.MEMBER_DATA

    def create(self, expire: int = 109500):
        '''
        Creates an RSA private key and X.509 cert

        :param int expire: days after which the cert should expire
        :returns: (none)
        :raises: ValueError if the Secret instance already
                            has a private key or cert

        '''

        common_name = (
            f'{self.member_id}.{IdType.MEMBER_DATA.value}{self.service_id}'
            f'.{self.network}'
        )
        super().create(common_name, expire=expire, key_size=4096, ca=self.ca)

    def create_csr(self) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param service_id: identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        # TODO: SECURITY: add constraints
        common_name = (
            f'{self.member_id}.{self.id_type.value}{self.service_id}'
            f'.{self.network}'
        )

        return super().create_csr(common_name, key_size=4096, ca=False)
