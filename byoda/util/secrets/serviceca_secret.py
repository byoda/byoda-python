'''
Cert manipulation for service secrets: Service CA, Service Members CA and
Service secret

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType, EntityId, CsrSource

from . import Secret

_LOGGER = logging.getLogger(__name__)


class ServiceCaSecret(Secret):
    def __init__(self, service: str, paths: Paths = None, network: str = None):
        '''
        Class for the Service CA secret. Either paths or network
        parameters must be provided. If paths parameter is not provided,
        the cert_file and private_key_file attributes of the instance must
        be set before the save() or load() members are called
        :param service: the label for the service
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

        self.service = service
        self.service_id = None

        if paths and network:
            raise ValueError('Either paths or network parameters must be set')

        if paths:
            self.network = paths.network
            super().__init__(
                cert_file=paths.get(
                    Paths.SERVICE_CA_CERT_FILE, service_alias=service
                ),
                key_file=paths.get(
                    Paths.SERVICE_CA_KEY_FILE, service_alias=service
                ),
                storage_driver=paths.storage_driver
            )
        else:
            self.network = network
            super().__init__(storage_driver=paths.storage_driver)

        self.ca = True
        self.id_type = IdType.SERVICE_CA

        self.csrs_accepted_for = ('members-ca')

    def create_csr(self, service_id: int) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR the the Service issuing CA

        :param service_id: identifier for the service
        :param expire: days after which the cert should expire
        :returns: csr
        :raises: ValueError if the Secret instance already has a private key
        or cert
        '''

        commonname = (
            f'{IdType.SERVICE_CA.value}{service_id}.{IdType.SERVICE.value}.'
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
                   source: CsrSource = CsrSource.WEBAPI) -> (str, str):
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
