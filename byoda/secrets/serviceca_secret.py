'''
Cert manipulation for service secrets: Service CA

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import TypeVar
from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType, EntityId, CsrSource

from .ca_secret import CaSecret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class ServiceCaSecret(CaSecret):
    def __init__(self, service: str, service_id: int, network: Network):
        '''
        Class for the Service CA secret. Either paths or network
        parameters must be provided. If paths parameter is not provided,
        the cert_file and private_key_file attributes of the instance must
        be set before the save() or load() members are called
        :returns: ValueError if both 'paths' and 'network' parameters are
        specified
        :raises: (none)
        '''

        self.service = str(service)
        self.service_id = int(service_id)

        if self.service_id < 0:
            raise ValueError(
                f'Service ID must be 0 or greater: {self.service_id}'
            )

        self.paths = network.paths
        self.paths.service_id = self.service_id

        self.network = network.name
        super().__init__(
            cert_file=self.paths.get(
                Paths.SERVICE_CA_CERT_FILE, service_id=self.service_id
            ),
            key_file=self.paths.get(
                Paths.SERVICE_CA_KEY_FILE, service_id=self.service_id
            ),
            storage_driver=self.paths.storage_driver
        )

        self.id_type = IdType.SERVICE_CA

        self.ca: bool = True
        self.signs_ca_certs: bool = True
        self.max_path_length: int = 1

        self.accepted_csrs = (
            IdType.MEMBERS_CA, IdType.APPS_CA, IdType.SERVICE,
            IdType.SERVICE_DATA,
        )

    def create_csr(self, source=CsrSource.LOCAL) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR for the Service issuing CA

        :returns: csr
        :raises: ValueError if the Secret instance already has a private key
        or cert
        '''

        # TODO: SECURITY: add constraints
        commonname = (
            f'service-ca.{self.id_type.value}{self.service_id}.'
            f'{self.network}'
        )

        return super().create_csr(commonname, key_size=4096, ca=self.ca)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an ServiceSecret or a MembersCaSecret. If so, it sets the 'service_id'
        property of the instance to the id parsed from the commonname

        :param commonname: the commonname to check
        :returns: service entity
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on the network postfix
        entity_id = super().review_commonname(
            commonname, uuid_identifier=False, check_service_id=False
        )

        return entity_id

    def review_csr(self, csr: CertificateSigningRequest,
                   source: CsrSource = CsrSource.WEBAPI) -> EntityId:
        '''
        Review a CSR. CSRs for register a service or or service_member_ca
        are permissable. Note that this function does not check whether the
        service identifier is already in use

        :param csr: cryptography.X509.CertificateSigningRequest
        :param source: source of the CSR
        :returns: Entity for the CSR
        :raises: ValueError if this object is not a CA (because it only has
        access to the cert and not the private_key) or if the CommonName is
        not valid in the CSR for signature by this CA
        '''

        if source != CsrSource.LOCAL:
            raise ValueError(
                'This CA does not accept CSRs received via an API call'
            )

        commonname = super().review_csr(csr)

        entity_id = self.review_commonname(commonname)

        return entity_id
