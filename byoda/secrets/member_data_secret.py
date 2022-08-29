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

from byoda import config

from .data_secret import DataSecret


_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')
Account = TypeVar('Account')


class MemberDataSecret(DataSecret):
    def __init__(self, member_id: UUID, service_id: int,
                 account: Account | None = None):
        '''
        Class for the member-data secret. This secret is used to encrypt
        data of an member of a service.
        :param member_id: the UUID for the membership
        :param service_id: the service id
        :param account: the account of the member
        :returns: ValueError if both 'paths' and 'network' parameters are
        specified
        :raises: (none)
        '''

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)
        self.member_id = member_id

        self.service_id = int(service_id)

        account_id = None
        if account:
            account_id = account.account_id

        network: Network = config.server.network
        self.paths = copy(network.paths)
        self.paths.service_id = self.service_id

        # secret.review_commonname requires self.network to be string
        self.network: str = config.server.network.name

        super().__init__(
            cert_file=self.paths.get(
                Paths.MEMBER_DATA_CERT_FILE,
                service_id=service_id, member_id=self.member_id,
                account_id=account_id
            ),
            key_file=self.paths.get(
                Paths.MEMBER_DATA_KEY_FILE,
                service_id=service_id, member_id=self.member_id,
                account_id=account_id
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

        common_name = MemberDataSecret.create_common_name(
            self.member_id, self.service_id, self.network
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

        common_name = MemberDataSecret.create_common_name(
            self.member_id, self.service_id, self.network
        )

        # TODO: SECURITY: add constraints
        return super().create_csr(common_name, key_size=4096, ca=False)

    @staticmethod
    def create_common_name(member_id: UUID, service_id: int,
                           network: Network | str) -> str:
        '''
        Creates a common name for a member-data secret
        :param member_id: identifier for the member
        :param service_id: identifier for the service
        :param network: name of the network
        :returns: common name
        :raises: (none)
        '''

        if not isinstance(network, str):
            network = network.name

        return f'{member_id}.{IdType.MEMBER_DATA.value}{service_id}.{network}'

    @staticmethod
    async def download(member_id: UUID, service_id: int,
                       network: Network | str):
        '''
        Downloads the member-data secret from the remote member

        :returns: MemberDataSecret
        '''

        if not isinstance(network, str):
            network = network.name

        member_data_secret = MemberDataSecret(member_id, service_id)

        try:
            url = Paths.resolve(
                Paths.MEMBER_DATACERT_DOWNLOAD, network=network,
                service_id=service_id, member_id=member_id
            )
            cert_data = await DataSecret.download(member_data_secret, url)
        except RuntimeError:
            # Pod may be down or disconnected, let's try the service server
            url = Paths.resolve(
                Paths.SERVICE_MEMBER_DATACERT_DOWNLOAD, network=network,
                service_id=service_id, member_id=member_id
            )
            _LOGGER.debug(
                'Falling back to downloading member data secret from service '
                'server'
            )
            cert_data = await DataSecret.download(member_data_secret, url)

        _LOGGER.debug(
            f'Downloaded member data secret for member {member_id} of '
            f'service {service_id} in network {network}'
        )

        member_data_secret.from_string(cert_data)

        return member_data_secret
