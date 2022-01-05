'''
Cert manipulation for service secrets: Apps CA

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import TypeVar
from copy import copy

from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType, EntityId
from .ca_secret import CaSecret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class AppsCaSecret(CaSecret):
    ACCEPTED_CSRS = [IdType.APP]

    def __init__(self, service: str, service_id: int,
                 network: Network):
        '''
        Class for the Service Apps CA secret. Either paths or network
        parameters must be provided. If paths parameter is not provided,
        the cert_file and private_key_file attributes of the instance must
        be set before the save() or load() apps are called

        :returns: ValueError if both 'paths' and 'network' parameters are
        specified
        :raises: (none)
        '''

        self.network = str(network.name)
        self.service_id = int(service_id)
        self.service = str(service)

        self.paths = copy(network.paths)
        self.paths.service_id = self.service_id

        super().__init__(
            cert_file=self.paths.get(
                Paths.SERVICE_APPS_CA_CERT_FILE, service_id=service_id
            ),
            key_file=self.paths.get(
                Paths.SERVICE_APPS_CA_KEY_FILE, service_id=service_id
            ),
            storage_driver=self.paths.storage_driver
        )

        self.id_type = IdType.APPS_CA

        # X.509 constraints
        self.ca = True
        self.max_path_length = 0

        self.signs_ca_certs = False
        self.accepted_csrs = AppsCaSecret.ACCEPTED_CSRS

    def create_csr(self) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param service_id: identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        # TODO: SECURITY: add constraints
        common_name = (
            f'apps-ca.{self.id_type.value}{self.service_id}.'
            f'{self.network}'
        )

        return super().create_csr(common_name, key_size=4096, ca=True)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an Appsecret. If so, it sets the 'uuid' property of the
        instance to the UUID parsed from the commonname.

        The first two levels of a commmon name for an app should be:
            {app_id}.apps-{service_id}

        :param commonname: the commonname to check
        :returns: entity parsed from the commonname
        :raises: ValueError, PermissionError
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
            commonname, network, AppsCaSecret.ACCEPTED_CSRS,
            service_id=service_id,
            uuid_identifier=True, check_service_id=True
        )

        return entity_id

    def review_csr(self, csr: CertificateSigningRequest) -> EntityId:
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
