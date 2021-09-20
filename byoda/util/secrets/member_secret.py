'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <steven@byoda.org>
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

        self.member_id = None
        if member_id:
            self.member_id = member_id

        self.service_id = int(service_id)

        self.paths = copy(account.paths)
        self.paths.service_id = self.service_id

        # secret.review_commonname requires self.network to be string
        self.network = account.network.name

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

        common_name = MemberSecret.create_fqdn(
            self.member_id, self.service_id, self.network
        )
        return super().create_csr(common_name, ca=self.ca)

    @staticmethod
    def create_fqdn(member_id: UUID, service_id: int, network: str):
        '''
        generates the FQDN for the common name in the Member TLS secret
        '''

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        service_id = int(service_id)
        if not isinstance(network, str):
            raise ('Network parameter must be a string')

        common_name = (
            f'{member_id}.{IdType.MEMBER.value}{service_id}.{network}'
        )

        return common_name

    def load(self, with_private_key: bool = True, password: str = 'byoda'):
        super().load(with_private_key=with_private_key, password=password)
        self.member_id = UUID(self.common_name.split('.')[0])
