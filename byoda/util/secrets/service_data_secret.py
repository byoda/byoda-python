'''
Cert manipulation for data of an account

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID
from typing import TypeVar
from copy import copy

from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType
from . import Secret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class ServiceDataSecret(Secret):
    def __init__(self, service, service_id, network: Network):
        '''
        Class for the account-data secret. This secret is used to encrypt
        account data.
        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :returns: ValueError if both 'paths' and 'network' parameters are
        specified
        :raises: (none)
        '''

        paths = copy(network.paths)
        self.service = str(service)
        self.service_id = int(service_id)
        paths.service_id = self.service_id

        super().__init__(
            cert_file=paths.get(Paths.SERVICE_DATA_CERT_FILE),
            key_file=paths.get(Paths.SERVICE_DATA_KEY_FILE),
            storage_driver=paths.storage_driver
        )
        self.network = paths.network
        self.id_type = IdType.SERVICE_DATA

        self.accepted_csrs = ()

    def create_csr(self, service_id: int = None) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param service_id: identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        if service_id:
            self.service_id = service_id

        common_name = (
            f'data.{self.id_type.value}{self.service_id}.{self.network}'
        )

        return super().create_csr(common_name, key_size=4096, ca=self.ca)
