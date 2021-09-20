'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from copy import copy

from uuid import UUID
from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType

from . import Secret

_LOGGER = logging.getLogger(__name__)


class MemberSecret(Secret):
    def __init__(self, service_id: int, paths: Paths):
        '''
        Class for the member secret of an account for a service

        :returns: (none)
        :raises: (none)
        '''

        self.paths = copy(paths)
        self.paths.service_id = service_id

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
            f'{member_id}.{self.id_type.value}{self.service_id}.{network}'
        )

        return super().create_csr(common_name, ca=self.ca)
