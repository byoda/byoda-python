'''
Cert manipulation of network secrets: root CA, accounts CA and services CA

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from copy import copy

from byoda.util import Paths

from byoda.datatypes import EntityId, IdType, CsrSource

from .secret import CSR
from .ca_secret import CaSecret

_LOGGER = logging.getLogger(__name__)


class NetworkServicesCaSecret(CaSecret):
    def __init__(self, paths=None):
        '''
        Class for the network services issuing CA secret

        :param Paths paths: instance of Paths class defining the directory
        structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.paths = copy(paths)
        self.network = paths.network

        super().__init__(
            cert_file=self.paths.get(Paths.NETWORK_SERVICES_CA_CERT_FILE),
            key_file=self.paths.get(Paths.NETWORK_SERVICES_CA_KEY_FILE),
            storage_driver=self.paths.storage_driver
        )

        self.id_type = IdType.SERVICES_CA

        self.signs_ca_certs = True
        self.accepted_csrs = [IdType.SERVICE_CA]

    def create_csr(self) -> CSR:
        '''
        Creates an RSA private key and X.509 CertificateSigningRequest

        :returns: csr
        :raises: ValueError if the Secret instance already has a
                            private key or cert
        '''

        common_name = (
            f'{self.id_type.value}.{self.id_type.value}.{self.network}'
        )

        return super().create_csr(common_name, key_size=4096, ca=True)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an ServiceCaSecret.

        :param commonname: the commonname to check
        :returns: services-ca entity
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        entity_id = super().review_commonname(
            commonname, uuid_identifier=False, check_service_id=False
        )

        return entity_id

    def review_csr(self, csr: CSR, source: CsrSource = None) -> EntityId:
        '''
        Review a CSR. CSRs from people wanting to register a service are
        permissable. Note that this function does not check whether the
        service identifier is already in use

        :param X509 csr         : cryptography.X509.CertificateSigningRequest
        :returns: entity, identifier
        :raises: ValueError if this object is not a CA
                                  (because it only has access to the cert and
                                  not the private_key) or if the CommonName
                                  is not valid in the CSR for signature by this
                                  CA
        '''

        commonname = super().review_csr(csr)

        entity_id = self.review_commonname(commonname)

        return entity_id
