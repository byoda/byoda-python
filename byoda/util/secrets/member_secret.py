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

from byoda.datatypes import IdType, EntityId, CsrSource

from . import Secret, CSR

_LOGGER = logging.getLogger(__name__)


class MemberSecret(Secret):
    def __init__(self, service_id: int, paths: Paths):
        '''
        Class for the member secret of an account for a service

        :returns: (none)
        :raises: (none)
        '''

        super().__init__(
            cert_file=paths.get(
                Paths.MEMBER_CERT_FILE, service_id=service_id
            ),
            key_file=paths.get(
                Paths.MEMBER_KEY_FILE, service_id=service_id
            ),
            storage_driver=paths.storage_driver
        )
        self.service_id = service_id
        self.ca = False
        self.id_type = IdType.MEMBER

    def create_csr(self, network: str, member_id: UUID,
                   expire: int = 3650) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param member_id: identifier of the member for the service
        :param expire: days after which the cert should expire
        :returns: csr
        :raises: ValueError if the Secret instance already has
        a private key or cert
        '''

        self.member_id = member_id

        common_name = (
            f'{member_id}_{self.service_id}.{self.id_type.value}.{network}'
        )

        return super().create_csr(common_name, ca=self.ca)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an MemberSecret

        :param commonname: the commonname to check
        :returns: entity with member uuid, service_id
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        commonname_prefix = super().review_commonname(commonname)

        bits = commonname_prefix.split('.')
        if len(bits) != 2:
            raise ValueError(f'Invalid number of domain levels: {commonname}')

        identifier, subdomain = bits[0:1]
        if subdomain != 'members':
            raise ValueError(f'commonname {commonname} is not for a member')

        user_id, service_id = identifier.split()
        try:
            uuid = UUID(user_id)
        except ValueError:
            raise ValueError(f'{user_id} is not a valid UUID')

        try:
            service_id = int(service_id)
        except ValueError:
            raise ValueError(f'Invalid service_id {service_id}')

        return EntityId(IdType.MEMBER, uuid, service_id)

    def review_csr(self, csr: CSR, source=CsrSource.WEBAPI):
        raise NotImplementedError
