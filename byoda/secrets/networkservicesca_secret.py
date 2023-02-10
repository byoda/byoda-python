'''
Cert manipulation of network secrets: root CA, accounts CA and services CA

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from copy import copy
from datetime import datetime, timedelta

from byoda.util.paths import Paths

from byoda.datatypes import EntityId, IdType
from byoda.datatypes import CsrSource

from .secret import CSR
from .ca_secret import CaSecret

_LOGGER = logging.getLogger(__name__)


class NetworkServicesCaSecret(CaSecret):
    # When should the Network Services CA secret be renewed
    RENEW_WANTED: datetime = datetime.now() + timedelta(days=180)
    RENEW_NEEDED: datetime = datetime.now() + timedelta(days=90)

    # CSRs that we are willing to sign and what we set for their expiration
    ACCEPTED_CSRS: dict[IdType, int] = {IdType.SERVICE_CA: 15 * 365}

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

        # X.509 constraints
        self.ca: bool = True
        self.max_path_length: int = 2

        self.accepted_csrs = self.ACCEPTED_CSRS

    async def create_csr(self, renew: bool = False) -> CSR:
        '''
        Creates an RSA private key and X.509 CertificateSigningRequest

        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: csr
        :raises: ValueError if the Secret instance already has a
                            private key or cert
        '''

        # TODO: SECURITY: add constraints
        common_name = (
            f'{self.id_type.value}.{self.id_type.value}.{self.network}'
        )

        return await super().create_csr(
            common_name, key_size=4096, ca=True, renew=renew
        )

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

    @staticmethod
    def review_commonname_by_parameters(commonname: str, network: str
                                        ) -> EntityId:
        '''
        Review the commonname for the specified network. Allows CNs to be
        reviewed without instantiating a class instance.

        :param commonname: the CN to check
        :raises: ValueError if the commonname is not valid for certs signed
        by instances of this class        '''

        entity_id = CaSecret.review_commonname_by_parameters(
            commonname, network, NetworkServicesCaSecret.ACCEPTED_CSRS,
            uuid_identifier=False, check_service_id=False
        )

        return entity_id

    def review_csr(self, csr: CSR, source: CsrSource = None) -> EntityId:
        '''
        Review a CSR. CSRs from people wanting to register a service are
        permissable. Note that this function does not check whether the
        service identifier is already in use

        :param csr: cryptography.X509.CertificateSigningRequest
        :returns: entity, identifier
        :raises: ValueError if this object is not a CA (because it only has
        access to the cert and not the private_key) or if the CommonName is
        not valid in the CSR for signature by this
                                  CA
        '''

        commonname = super().review_csr(csr)

        entity_id = self.review_commonname(commonname)

        return entity_id
