'''
Cert manipulation of network secrets: root CA, accounts CA and services CA

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from copy import copy
from typing import override
from logging import Logger
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from byoda.util.paths import Paths

from byoda.datatypes import IdType, EntityId
from byoda.datatypes import CsrSource

from .ca_secret import CaSecret

from .secret import CSR

_LOGGER: Logger = getLogger(__name__)


class NetworkAccountsCaSecret(CaSecret):
    __slots__: list[str] = ['network']

    # When should the Network Accounts CA secret be renewed
    RENEW_WANTED: datetime = datetime.now(tz=UTC) + timedelta(days=180)
    RENEW_NEEDED: datetime = datetime.now(tz=UTC) + timedelta(days=90)

    # CSRs that we are willing to sign and what we set for their expiration
    _ACCEPTED_CSRS: dict[IdType, int] = {
        IdType.ACCOUNT: 365,
        IdType.ACCOUNT_DATA: 365
    }

    # There are no CAs allowed under the accounts CA
    _PATHLEN = 0

    @override
    def __init__(self, paths: Paths = None, network: str = None) -> None:
        '''
        Class for the network account CA secret. Either paths or network
        parameters must be provided. If paths parameter is not provided,
        the cert_file and private_key_file attributes of the instance must
        be set before the save() or load() members are called

        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :param network: name of the network
        :returns: (none)
        :raises: ValueError if both paths and network are defined
        '''

        if paths and network:
            raise ValueError('Either paths or network parameters must be set')

        if paths:
            self.paths = copy(paths)
            self.network: str = paths.network
            super().__init__(
                cert_file=self.paths.get(Paths.NETWORK_ACCOUNTS_CA_CERT_FILE),
                key_file=self.paths.get(Paths.NETWORK_ACCOUNTS_CA_KEY_FILE),
                storage_driver=self.paths.storage_driver,
            ),
        else:
            super().__init__()
            self.network = network
            self.paths = None

        self.id_type = IdType.ACCOUNTS_CA

        # X.509 constraints
        self.ca = True
        self.max_path_length = self._PATHLEN

        self.accepted_csrs = NetworkAccountsCaSecret._ACCEPTED_CSRS

    @override
    async def create_csr(self, renew: bool = False) -> CSR:
        '''
        Creates an RSA private key and X.509 cert signature request

        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: csr
        :raises: ValueError if the Secret instance already has a cert or a
                 private key

        '''

        commonname: str = (
            f'{self.id_type.value}.{self.id_type.value}.{self.network}'
        )

        return await super().create_csr(commonname, renew=renew)

    @override
    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an AccountSecret. If so, it sets the 'account_id' property of the
        instance to the UUID parsed from the commonname

        :param commonname: the CN to check
        :raises: ValueError if the commonname is not valid for certs signed
        by instances of this class
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
            commonname, network, NetworkAccountsCaSecret._ACCEPTED_CSRS,
            uuid_identifier=True, check_service_id=False
        )

        return entity_id

    @override
    def review_csr(self, csr: CSR, source: CsrSource = None) -> EntityId:
        '''
        Review a CSR. CSRs from people wanting to register an account are
        permissable.

        :param X509 csr: cryptography.X509.CertificateSigningRequest
        :returns: entity, identifier
        :raises: ValueError if this object is not a CA (because it only has
        access to the cert and not the private_key) or if the CommonName
        is not valid in the CSR for signature by this CA
        '''

        if not self.private_key_file:
            _LOGGER.exception('CSR received while we are not a CA')
            raise ValueError('CSR received while we are not a CA')

        commonname: str = super().review_csr(csr)

        entity_id: EntityId = self.review_commonname(commonname)

        return entity_id
