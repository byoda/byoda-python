'''
Cert manipulation for data of an account

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from copy import copy
from typing import override
from logging import Logger
from logging import getLogger

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType
from .data_secret import DataSecret

_LOGGER: Logger = getLogger(__name__)


class NetworkDataSecret(DataSecret):
    __slots__: list[str] = ['network']

    @override
    def __init__(self, paths: Paths) -> None:
        '''
        Class for the Network Data secret. This secret is used to sign
        documentslike the list of services in the network
        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :raises: ValueError if both 'paths' and 'network' parameters are
        specifiedq
        '''

        self.network: str = paths.network
        self.paths = copy(paths)
        super().__init__(
            cert_file=self.paths.get(Paths.NETWORK_DATA_CERT_FILE),
            key_file=self.paths.get(Paths.NETWORK_DATA_KEY_FILE),
            storage_driver=self.paths.storage_driver
        )

        self.id_type: IdType = IdType.NETWORK_DATA

    @override
    async def create(self, expire: int = 1085) -> None:
        '''
        Creates an RSA private key and X.509 cert

        :param int expire: days after which the cert should expire
        :returns: (none)
        :raises: ValueError if the Secret instance already
                            has a private key or cert

        '''

        common_name: str = f'{self.account_id}.network_data.{self.network}'
        await super().create(
            common_name, expire=expire, key_size=4096, ca=self.ca
        )

    @override
    async def create_csr(self, network: str = None, renew: bool = False
                         ) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param network: the name of the network
        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        if not network:
            network = self.network

        common_name: str = (
            f'network.{IdType.NETWORK_DATA.value}.{network}'
        )

        return await super().create_csr(common_name, renew=renew)
