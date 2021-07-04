'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID
from copy import copy
from typing import TypeVar

from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType

from . import Secret

_LOGGER = logging.getLogger(__name__)

Account = TypeVar('Account', bound='Account')


class MemberSecret(Secret):
    def __init__(self, member_id: UUID, service_id: int, account: Account):
        '''
        Class for the member secret of an account for a service

        :returns: (none)
        :raises: (none)
        '''

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)
        self.member_id = member_id

        self.service_id = int(service_id)

        self.paths = copy(account.paths)
        self.paths.service_id = self.service_id

        # secret.review_commonname requires self.network to be string
        self.network = account.network.network

        super().__init__(
            cert_file=self.paths.get(
                Paths.MEMBER_CERT_FILE,
                service_id=service_id, member_id=self.member_id,
            ),
            key_file=self.paths.get(
                Paths.MEMBER_KEY_FILE,
                service_id=service_id, member_id=self.member_id,
            ),
            storage_driver=self.paths.storage_driver
        )

        self.id_type = IdType.MEMBER

    def create_csr(self) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param member_id: identifier of the member for the service
        :param expire: days after which the cert should expire
        :returns: csr
        :raises: ValueError if the Secret instance already has
        a private key or cert
        '''

        common_name = (
            f'{self.member_id}.{self.id_type.value}{self.service_id}.'
            f'{self.network}'
        )

        return super().create_csr(common_name, ca=self.ca)
