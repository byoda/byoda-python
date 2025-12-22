'''
Cert manipulation of network secrets: root CA, accounts CA and services CA

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from copy import copy
from typing import TypeVar
from typing import override
from logging import Logger
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from byoda.util.paths import Paths

from byoda.datatypes import EntityId, IdType
from byoda.datatypes import CsrSource

from .secret import CSR
from .ca_secret import CaSecret

_LOGGER: Logger = getLogger(__name__)

Network = TypeVar('Network')


class NetworkServicesCaSecret(CaSecret):
    __slots__: list[str] = ['network']

    # When should the Network Services CA secret be renewed
    RENEW_WANTED: datetime = datetime.now(tz=UTC) + timedelta(days=180)
    RENEW_NEEDED: datetime = datetime.now(tz=UTC) + timedelta(days=90)

    # CSRs that we are willing to sign and what we set for their expiration
    _ACCEPTED_CSRS: dict[IdType, int] = {IdType.SERVICE_CA: 15 * 365}

    # The longest path under network services CA is:
    #   -> service_ca -> members_ca
    _PATHLEN = 2

    def __init__(self, paths=None) -> None:
        '''
        Class for the network services issuing CA secret

        :param Paths paths: instance of Paths class defining the directory
        structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.paths = copy(paths)
        self.network: Network = paths.network

        super().__init__(
            cert_file=self.paths.get(Paths.NETWORK_SERVICES_CA_CERT_FILE),
            key_file=self.paths.get(Paths.NETWORK_SERVICES_CA_KEY_FILE),
            storage_driver=self.paths.storage_driver
        )

        self.id_type = IdType.SERVICES_CA

        # X.509 constraints
        self.ca: bool = True
        self.max_path_length: int = self._PATHLEN

        self.accepted_csrs = self._ACCEPTED_CSRS

    @override
    async def create_csr(self, renew: bool = False) -> CSR:
        '''
        Creates an RSA private key and X.509 CertificateSigningRequest

        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: csr
        :raises: ValueError if the Secret instance already has a
                            private key or cert
        '''

        common_name: str = (
            f'{self.id_type.value}.{self.id_type.value}.{self.network}'
        )

        return await super().create_csr(common_name, renew=renew)

    @override
    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an ServiceCaSecret.

        :param commonname: the commonname to check
        :returns: services-ca entity
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        entity_id: str = super().review_commonname(
            commonname, uuid_identifier=False, check_service_id=False
        )

        return entity_id

    @override
    @staticmethod
    def review_commonname_by_parameters(commonname: str, network: str
                                        ) -> EntityId:
        '''
        Review the commonname for the specified network. Allows CNs to be
        reviewed without instantiating a class instance.

        :param commonname: the CN to check
        :raises: ValueError if the commonname is not valid for certs signed
        by instances of this class        '''

        entity_id: EntityId = CaSecret.review_commonname_by_parameters(
            commonname, network, NetworkServicesCaSecret._ACCEPTED_CSRS,
            uuid_identifier=False, check_service_id=False
        )

        return entity_id

    @override
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

        commonname: str = super().review_csr(csr)

        entity_id: EntityId = self.review_commonname(commonname)

        return entity_id
