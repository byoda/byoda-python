'''
Cert manipulation for service secrets: Service CA, Service Members CA and
Service secret

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import TypeVar

from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType, EntityId

from . import Secret


_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class ServiceSecret(Secret):
    def __init__(self, service: str, service_id: int, network: Network):
        '''
        Class for the service secret

        :param Paths paths: instance of Paths class defining the directory,
        structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        paths = network.paths
        self.network = network.network
        self.service = str(service)
        self.service_id = int(service_id)

        super().__init__(
            cert_file=paths.get(
                Paths.SERVICE_CERT_FILE, service_id=self.service_id
            ),
            key_file=paths.get(
                Paths.SERVICE_KEY_FILE, service_id=self.service_id
            ),
            storage_driver=paths.storage_driver
        )
        self.ca = False
        self.id_type = IdType.SERVICE

    def create_csr(self) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param service_id: identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has a private key
        or cert
        '''

        common_name = (
            f'service.{self.id_type.value}{self.service_id}.{self.network}'
        )

        return super().create_csr(common_name, ca=self.ca)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an ServiceSecret and returns the entity identifier parsed from
        the commonname

        :param commonname: the commonname to check
        :returns: service entity
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        entity_id = super().review_commonname(commonname)

        return entity_id
