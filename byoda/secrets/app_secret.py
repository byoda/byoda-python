'''
Cert manipulation for apps

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
from copy import copy
from uuid import UUID
from datetime import datetime, timedelta

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType

from . import Secret

_LOGGER = logging.getLogger(__name__)


class AppSecret(Secret):
    '''
    The account secret is used as TLS secret on the Account API endpoint
    of the pod
    '''

    # When should the secret be renewed
    RENEW_WANTED: datetime = datetime.now() + timedelta(days=90)
    RENEW_NEEDED: datetime = datetime.now() + timedelta(days=30)

    def __init__(self, service_id: int, paths: Paths):
        '''
        Class for the member secret of an account for a service

        :returns: (none)
        :raises: (none)
        '''

        service_id = int(service_id)

        self.paths: Paths = copy(paths)
        self.paths.service_id: int = service_id

        super().__init__(
            cert_file=paths.get(
                Paths.MEMBER_CERT_FILE, service_id=service_id
            ),
            key_file=paths.get(
                Paths.MEMBER_KEY_FILE, service_id=service_id
            ),
            storage_driver=paths.storage_driver
        )
        self.service_id: int = service_id
        self.ca: bool = False
        self.id_type: IdType = IdType.MEMBER

    async def create_csr(self, network: str, member_id: UUID,
                         renew: bool = False) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param network: name of the network
        :param member_id: identifier of the member for the service
        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: csr
        :raises: ValueError if the Secret instance already has
        a private key or cert
        '''

        self.member_id = member_id

        # TODO: SECURITY: add constraints
        common_name = (
            f'{member_id}.{self.id_type.value}{self.service_id}.{network}'
        )

        return await super().create_csr(common_name, ca=self.ca, renew=renew)
