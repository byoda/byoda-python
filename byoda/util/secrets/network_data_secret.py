'''
Cert manipulation for data of an account

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from copy import copy

from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType
from . import Secret

_LOGGER = logging.getLogger(__name__)


class NetworkDataSecret(Secret):
    def __init__(self, paths: Paths):
        '''
        Class for the Network Data secret. This secret is used to sign
        documentslike the list of services in the network
        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :raises: ValueError if both 'paths' and 'network' parameters are
        specified
        '''

        self.network = paths.network
        self.paths = copy(paths)
        super().__init__(
            cert_file=self.paths.get(Paths.NETWORK_DATA_CERT_FILE),
            key_file=self.paths.get(Paths.NETWORK_DATA_KEY_FILE),
            storage_driver=self.paths.storage_driver
        )
        self.ca = False
        self.is_root_cert = False
        self.issuing_ca = None
        self.id_type = IdType.NETWORK_DATA

        self.accepted_csrs = ()

    def create(self, expire: int = 1085):
        '''
        Creates an RSA private key and X.509 cert

        :param int expire: days after which the cert should expire
        :returns: (none)
        :raises: ValueError if the Secret instance already
                            has a private key or cert

        '''

        common_name = f'{self.account_id}.network_data.{self.network}'
        super().create(common_name, expire=expire, key_size=4096, ca=self.ca)

    def create_csr(self, network: str = None) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param service_id: identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        if not network:
            network = self.network

        common_name = (
            f'network.{IdType.NETWORK_DATA.value}.{network}'
        )

        return super().create_csr(common_name, key_size=4096, ca=self.ca)
