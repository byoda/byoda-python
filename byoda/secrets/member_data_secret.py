'''
Cert manipulation for data of an account

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from copy import copy
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType

from byoda import config

from .data_secret import DataSecret
from .data_secret import Secret


_LOGGER: Logger = getLogger(__name__)

Network = TypeVar('Network')
Account = TypeVar('Account')


class MemberDataSecret(DataSecret):
    __slots__ = ['member_id', 'network', 'service_id']

    def __init__(self, member_id: UUID, service_id: int,
                 account: Account | None = None):
        '''
        Class for the member-data secret. This secret is used to encrypt
        data of an member of a service.

        :param member_id: the UUID for the membership
        :param service_id: the service id
        :param account: the account of the member
        :raises: ValueError if both 'paths' and 'network' parameters are
        specified
        :raises: (none)
        '''

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        self.member_id: UUID = member_id

        service_id = int(service_id)

        account_id: UUID | None = None
        if account:
            account_id: UUID = account.account_id

        network: Network = config.server.network
        self.paths: Paths = copy(network.paths)
        self.paths.service_id: int = service_id

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

        self.service_id: int = service_id
        self.id_type: IdType = IdType.MEMBER_DATA

    async def create(self, expire: int = 109500):
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
        await super().create(
            common_name, expire=expire, key_size=4096, ca=self.ca
        )

    async def create_csr(self, renew: bool = False
                         ) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        common_name = MemberDataSecret.create_common_name(
            self.member_id, self.service_id, self.network
        )

        # TODO: SECURITY: add constraints
        return await super().create_csr(
            common_name, key_size=4096, ca=False, renew=renew
        )

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

        service_id = int(service_id)

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

        service_id = int(service_id)
        member_data_secret = MemberDataSecret(member_id, service_id)

        try:
            url = Paths.resolve(
                Paths.MEMBER_DATACERT_DOWNLOAD, network=network,
                service_id=service_id, member_id=member_id
            )
            cert_data = await DataSecret.download(
                member_data_secret, url, network_name=network
            )
            _LOGGER.debug(
                f'Downloaded member data secret of {len(cert_data or "")} '
                f'bytes from pod: {url}'
            )
        except RuntimeError:
            # Pod may be down or disconnected, let's try the service server
            url = Paths.resolve(
                Paths.SERVICE_MEMBER_DATACERT_DOWNLOAD, network=network,
                service_id=service_id, member_id=member_id
            )
            cert_data = await DataSecret.download(member_data_secret, url)
            _LOGGER.debug(
                'Falling back to downloading member data secret of '
                f'{len(cert_data or "")} bytes from service server {url}'
            )

        _LOGGER.debug(
            f'Downloaded member data secret for member {member_id} of '
            f'service {service_id} in network {network}'
        )

        member_data_secret.from_string(cert_data)

        return member_data_secret

    def from_string(self, cert: str, certchain: str = None):
        '''
        Loads an X.509 cert and certchain from a string. If the cert has an
        certchain then the certchain can either be included at the end
        of the string of the cert or can be provided as a separate parameter

        :param cert: the base64-encoded cert
        :param certchain: the base64-encoded certchain
        :returns: (none)
        :raises: (none)
        '''

        super().from_string(cert, certchain)

        self.common_name = Secret.extract_commonname(self.cert)
