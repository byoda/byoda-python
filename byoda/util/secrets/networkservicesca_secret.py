'''
Cert manipulation of network secrets: root CA, accounts CA and services CA

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from byoda.util import Paths

from byoda.datatypes import EntityId, IdType

from . import Secret, CSR

_LOGGER = logging.getLogger(__name__)


class NetworkServicesCaSecret(Secret):
    def __init__(self, paths=None):
        '''
        Class for the network services issuing CA secret

        :param Paths paths       : instance of Paths class defining the
                                   directory structure and file names of a
                                   BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.network = paths.network
        super().__init__(
            cert_file=paths.get(Paths.NETWORK_SERVICES_CA_CERT_FILE),
            key_file=paths.get(Paths.NETWORK_SERVICES_CA_KEY_FILE),
            storage_driver=paths.storage_driver
        )

        self.ca = True
        self.id_type = IdType.SERVICES_CA

        self.csrs_accepted_for = 'service-issuing'

    def create_csr(self) -> CSR:
        '''
        Creates an RSA private key and X.509 CertificateSigningRequest

        :returns: csr
        :raises: ValueError if the Secret instance already has a
                            private key or cert
        '''

        common_name = f'{IdType.SERVICES_CA.value}.{self.network}'

        return super().create_csr(common_name, key_size=4096, ca=True)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an ServiceCaSecret. If so, it sets the 'account_id' property of the
        instance to the UUID parsed from the commonname

        :param commonname: the commonname to check
        :returns: services-ca entity
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        commonname_prefix = super().review_commonname(commonname)

        if not commonname_prefix.startswith(IdType.SERVICE_CA.value):
            raise ValueError(
                f'Service CA common name {commonname_prefix} does not start '
                f'with "ca-"'
            )

        bits = commonname_prefix.split('.')
        if len(bits) != 2:
            raise ValueError(f'Invalid number of domain levels: {commonname}')

        service_id, subdomain = bits

        try:
            id_type = IdType(subdomain)
        except ValueError:
            raise ValueError(f'Invalid subdomain {subdomain} in commonname')

        if (id_type != IdType.SERVICE
                or not service_id.startswith(IdType.SERVICE_CA.value)):
            raise ValueError(f'commonname {commonname} is not for a ServiceCA')

        service_id = service_id[len(IdType.SERVICE_CA.value):]
        if not service_id.isdigit():
            raise ValueError(
                f'Service dentifier in {commonname} must be all-digits: '
                f'{service_id}'
            )

        return EntityId(id_type, None, service_id)

    def review_csr(self, csr):
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

        if not self.private_key_file:
            _LOGGER.exception('CSR received while we are not a CA')
            raise ValueError('CSR received while we are not a CA')

        commonname = super().review_csr(csr)

        entity_id = self.review_commonname(commonname)

        return entity_id
