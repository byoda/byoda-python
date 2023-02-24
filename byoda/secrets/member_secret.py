'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
from uuid import UUID
from copy import copy
from typing import TypeVar

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType

from . import Secret

_LOGGER = logging.getLogger(__name__)

Account = TypeVar('Account')
Network = TypeVar('Network')


class MemberSecret(Secret):
    def __init__(self, member_id: UUID, service_id: int, account: Account):
        '''
        Class for the member secret of an account for a service

        :returns: (none)
        :raises: (none)
        '''

        self.member_id = None
        if member_id:
            self.member_id: UUID = member_id

        service_id = int(service_id)

        self.paths: Paths = copy(account.paths)
        self.paths.service_id: int = service_id

        # secret.review_commonname requires self.network to be string
        self.network: str = account.network.name

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

        self.service_id: int = service_id
        self.id_type: IdType = IdType.MEMBER

    async def create_csr(self, renew: bool = False
                         ) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param member_id: identifier of the member for the service
        :param renew: if True, renew the secret using the existing private key
        :returns: csr
        :raises: ValueError if the Secret instance already has
        a private key or cert
        '''

        # TODO: SECURITY: add constraints
        common_name: str = MemberSecret.create_commonname(
            self.member_id, self.service_id, self.network
        )
        return await super().create_csr(common_name, ca=self.ca, renew=renew)

    @staticmethod
    def create_commonname(member_id: UUID, service_id: int, network: str):
        '''
        generates the FQDN for the common name in the Member TLS secret
        '''

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        service_id = int(service_id)
        if not isinstance(network, str):
            raise TypeError(
                f'Network parameter must be a string, not a {type(network)}'
            )

        common_name = (
            f'{member_id}.{IdType.MEMBER.value}{service_id}.{network}'
        )

        return common_name

    async def load(self, with_private_key: bool = True,
                   password: str = 'byoda'):
        await super().load(
            with_private_key=with_private_key, password=password
        )
        self.member_id = UUID(self.common_name.split('.')[0])

    def save_tmp_private_key(self):
        '''
        Save the private key for the MemberSecret so nginx and the python
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

        return f'/var/tmp/private-member-{self.member_id}.key'
