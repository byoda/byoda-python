'''
Cert manipulation for service secrets: Service CA, Service Members CA and
Service secret

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from copy import copy
from typing import TypeVar

from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType, EntityId, CsrSource

from .ca_secret import CaSecret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class MembersCaSecret(CaSecret):
    ACCEPTED_CSRS = [IdType.MEMBER, IdType.MEMBER_DATA]

    def __init__(self, service: str, service_id: int, network: Network):
        '''
        Class for the Service Members CA secret.

        The first two levels of a commmon name for a member should be:
            {member_id}.members-ca-{service_id}
        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :param service: label for the service
        :param paths: object containing all the file paths for the network. If
        this parameter has a value then the 'network' parameter must be None
        :param network: name of the network. If this parameter has a value then
        the 'paths' parameter must be None
        :returns: ValueError if both 'paths' and 'network' parameters are
        specified
        :raises: (none)
        '''

        self.network = str(network.name)
        self.service_id = int(service_id)

        self.paths = copy(network.paths)
        self.paths.service_id = self.service_id

        super().__init__(
            cert_file=self.paths.get(
                Paths.SERVICE_MEMBERS_CA_CERT_FILE, service_id=service_id
            ),
            key_file=self.paths.get(
                Paths.SERVICE_MEMBERS_CA_KEY_FILE, service_id=service_id
            ),
            storage_driver=self.paths.storage_driver
        )

        self.id_type = IdType.MEMBERS_CA

        self.accepted_csrs = MembersCaSecret.ACCEPTED_CSRS

    def create_csr(self) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param service_id: identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        name = self.id_type.value.rstrip('-')
        common_name = (
            f'{name}.{self.id_type.value}{self.service_id}.'
            f'{self.network}'
        )

        return super().create_csr(common_name, key_size=4096, ca=True)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an MemberSecret.

        :param commonname: the commonname to check
        :returns: entity parsed from the commonname
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        entity_id = super().review_commonname(commonname)

        return entity_id

    @staticmethod
    def review_commonname_by_parameters(commonname: str, network: str,
                                        service_id: int) -> EntityId:
        '''
        Review the commonname for the specified network. Allows CNs to be
        reviewed without instantiating a class instance.

        :param commonname: the CN to check
        :raises: ValueError if the commonname is not valid for certs signed
        by instances of this class        '''

        entity_id = CaSecret.review_commonname_by_parameters(
            commonname, network, MembersCaSecret.ACCEPTED_CSRS,
            service_id=service_id, uuid_identifier=True, check_service_id=True
        )

        return entity_id

    def review_csr(self, csr: CertificateSigningRequest,
                   source: CsrSource = None) -> EntityId:
        '''
        Review a CSR. CSRs for registering service member are permissable.

        :param csr: CSR to review
        :returns: entity, identifier
        :raises: ValueError if this object is not a CA (because it only has
        access to the cert and not the private_key) or if the CommonName
        in the CSR is not valid for signature by this CA
        '''

        if not self.private_key_file:
            _LOGGER.exception('CSR received while we are not a CA')
            raise ValueError('CSR received while we are not a CA')

        commonname = super().review_csr(csr)

        entity_id = self.review_commonname(commonname)

        return entity_id
