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

from byoda.datatypes import IdType, EntityId, CsrSource

from . import Secret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class ServiceCaSecret(Secret):
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
            raise ValueError(f'Service ID must be 0 or greater')

        paths = network.paths
        self.network = network.network
        super().__init__(
            cert_file=paths.get(
                Paths.SERVICE_CA_CERT_FILE, service_id=self.service_id
            ),
            key_file=paths.get(
                Paths.SERVICE_CA_KEY_FILE, service_id=self.service_id
            ),
            storage_driver=paths.storage_driver
        )

        self.ca = True
        self.id_type = IdType.SERVICE_CA

        self.csrs_accepted_for = (
            IdType.MEMBERS_CA.value, IdType.APPS_CA.value,
        )

    def create_csr(self) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR the the Service issuing CA

        :param expire: days after which the cert should expire
        :returns: csr
        :raises: ValueError if the Secret instance already has a private key
        or cert
        '''

        commonname = (
            f'{IdType.SERVICE_CA.value}{self.service_id}.{IdType.SERVICE.value}.'
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

        # Checks on commonname type and the network postfix
        commonname_prefix = super().review_commonname(commonname)

        # There are two types of CSRs for this CA:
        #   - the CSR for the service certificate
        #     format: {service_id}.services.{network}
        #   - the CSR for the members-ca for the service.
        #     format: members-ca-{service_id}.services.{network}

        bits = commonname_prefix.split('.')
        if len(bits) != 2:
            raise ValueError(f'Invalid number of domain levels: {commonname}')

        identifier, subdomain = bits
        try:
            id_type = IdType(subdomain)
        except ValueError:
            raise ValueError(f'Invalid subdomain in commonname {commonname}')

        if id_type != IdType.SERVICE:
            raise ValueError(f'commonname {commonname} is not for a service')

        if identifier.startswith(IdType.MEMBERS_CA.value):
            id_type = IdType.MEMBERS_CA
            service_id = identifier[len(IdType.MEMBERS_CA.value):]
        else:
            service_id = identifier

        if not service_id.isdigit():
            raise ValueError(
                f'Service_id for {id_type.value} in commonname {commonname} '
                'must only contain digits'
            )

        return EntityId(id_type, None, int(service_id))

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

        if not self.private_key_file:
            raise ValueError(
                'CSR received while we do not have the private key for this CA'
            )

        if source == CsrSource.WEBAPI:
            raise ValueError(
                'This CA does not accept CSRs received via API call'
            )

        commonname = super().review_csr(csr)

        entityid = self.review_commonname(commonname)

        return entityid
