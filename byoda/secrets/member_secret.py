'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from copy import copy
from typing import Self
from typing import TypeVar
from logging import getLogger

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType
from byoda.datatypes import TEMP_SSL_DIR

from byoda.util.logger import Logger

from .secret import Secret

_LOGGER: Logger = getLogger(__name__)

Account = TypeVar('Account')
Network = TypeVar('Network')


class MemberSecret(Secret):
    __slots__: list[str] = ['member_id', 'network', 'service_id', 'account_id']

    def __init__(self, member_id: UUID, service_id: int,
                 account: Account | None = None, paths: Paths = None,
                 network_name: str = None) -> None:
        '''
        Class for the member secret of an account for a service

        :param member_id: the UUID for the membership
        :param service_id: the service id
        :param account: the account of the member
        :param paths: Paths instance
        :param network_name: name of the network
        :raises: ValueError if both 'paths' and 'network' parameters are
        specified
        '''

        if paths is None and account is None:
            raise ValueError(
                'Either paths or account must be specified'
            )

        if paths is None:
            paths = account.paths

        if network_name is None and account is None:
            raise ValueError(
                'Either network_name or account must be specified'
            )

        self.account_id = None
        if account:
            self.account_id: UUID = account.account_id

        if network_name is None:
            network_name = account.network.name

        self.member_id = None
        if member_id:
            self.member_id: UUID = member_id

        service_id = int(service_id)

        self.paths: Paths = copy(paths)
        self.paths.service_id: int = service_id

        # secret.review_commonname requires self.network to be string
        self.network: str = network_name

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
    def create_commonname(member_id: UUID, service_id: int, network: str) -> str:
        '''
        generates the FQDN for the common name in the Member TLS secret
        '''

        if not member_id:
            raise ValueError('Member ID must be specified')

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
                   password: str = 'byoda') -> None:
        await super().load(
            with_private_key=with_private_key, password=password
        )
        self.member_id = UUID(self.common_name.split('.')[0])

    def save_tmp_private_key(self) -> str:
        '''
        Save the private key for the MemberSecret so angie and the python
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

        return (
            f'{TEMP_SSL_DIR}/{self.account_id}/'
            f'private-member-{self.member_id}.key'
        )

    @staticmethod
    async def download(member_id: UUID, service_id: int,
                       network: Network | str, paths: Paths,
                       root_ca_cert_file: str) -> Self:
        '''
        Factory that downloads the member-data secret from the remote member

        :returns: MemberSecret
        '''

        if not isinstance(network, str):
            network = network.name

        service_id = int(service_id)
        member_secret = MemberSecret(
            member_id, service_id, None, paths=paths, network_name=network
        )

        try:
            url = Paths.resolve(
                Paths.MEMBER_CERT_DOWNLOAD, network=network,
                service_id=service_id, member_id=member_id
            )
            cert_data = await Secret.download(
                url, root_ca_filepath=root_ca_cert_file
            )
        except RuntimeError:
            # Pod may be down or disconnected, let's try the service server
            url = Paths.resolve(
                Paths.SERVICE_MEMBER_CERT_DOWNLOAD, network=network,
                service_id=service_id, member_id=member_id
            )
            _LOGGER.debug(
                'Falling back to downloading member data secret from service '
                'server'
            )
            cert_data = await Secret.download(
                url, root_ca_filepath=root_ca_cert_file
            )
            _LOGGER.debug(
                'Falling back to downloading member data secret of '
                f'{len(cert_data or "")} bytes from service server {url}'
            )
        _LOGGER.debug(
            f'Downloaded member data secret for member {member_id} of '
            f'service {service_id} in network {network}'
        )

        member_secret.from_string(cert_data)
        await member_secret.save(overwrite=True)

        return member_secret
