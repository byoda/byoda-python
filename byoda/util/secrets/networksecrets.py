'''
Cert manipulation of network secrets: root CA, accounts CA and services CA

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID

from byoda.util import Paths

from . import Secret, CsrSource

_LOGGER = logging.getLogger(__name__)


class NetworkRootCaSecret(Secret):
    def __init__(self, paths):
        '''
        Class for the network root CA secret

        :param Paths paths  : instance of Paths class defining the directory
                              structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.network = paths.network
        super().__init__(
            cert_file=paths.get(Paths.NETWORK_ROOT_CA_CERT_FILE),
            key_file=paths.get(Paths.NETWORK_ROOT_CA_KEY_FILE)
        )

        self.ca = True
        self.issuing_ca = None
        self.csrs_accepted_for = (
            'accounts-ca', 'services-ca'
        )

    def create(self, expire=10950):
        '''
        Creates an RSA private key and X.509 cert

        :param int expire: days after which the cert should expire
        :returns: (none)
        :raises: ValueError if the Secret instance already
                            has a private key or cert

        '''

        common_name = f'root-ca.{self.network}'
        super().create(common_name, expire=expire, key_size=4096, ca=self.ca)

    def create_csr(self):
        raise NotImplementedError

    def review_csr(self, csr, source=CsrSource.WEBAPI):
        '''
        Review a CSR. CSRs from NetworkAccountCA and NetworkServicesCA are
        permissable.

        :param X509 csr: cryptography.X509.CertificateSigningRequest
        :param CsrSource source: source of the CSR
        :returns: tupple of entity ['accounts-ca' or 'services-ca'], None
        :raises: ValueError if this object is not a CA because it only has
                 access to the cert and not the private_key) or if the
                 CommonName is not valid in the CSR for signature by this CA
        '''

        if not self.private_key_file:
            _LOGGER.exception('CSR received while we are not a CA')
            raise ValueError('CSR received while we are not a CA')

        if source == CsrSource.WEBAPI:
            _LOGGER.warning(
                'This CA does not accept CSRs received via API call'
            )
            raise ValueError(
                'This CA does not accept CSRs received via API call'
            )

        common_name_prefix = super().review_csr(csr)

        if common_name_prefix not in self.csrs_accepted_for:
            _LOGGER.warning(
                'Common name prefix %s does not match one of: %s',
                common_name_prefix, ', '.join(self.csrs_accepted_for))

        return common_name_prefix, None


class NetworkAccountsCaSecret(Secret):
    def __init__(self, paths=None):
        '''
        Class for the network root CA secret

        :param Paths paths: instance of Paths class defining the directory
                            structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.network = paths.network
        super().__init__(
            cert_file=paths.get(Paths.NETWORK_ACCOUNTS_CA_CERT_FILE),
            key_file=paths.get(Paths.NETWORK_ACCOUNTS_CA_KEY_FILE),
        )

        self.ca = True

        self.csrs_accepted_for = ('account')

    def create_csr(self):
        '''
        Creates an RSA private key and X.509 cert signature request

        :returns: csr
        :raises: ValueError if the Secret instance already has a cert or a
                 private key

        '''

        common_name = f'accounts-ca.{self.network}'

        return super().create_csr(common_name, key_size=4096, ca=self.ca)

    def review_csr(self, csr):
        '''
        Review a CSR. CSRs from people wanting to register an account are
        permissable.

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

        common_name_prefix = super().review_csr(csr)

        entity = 'account'
        if not common_name_prefix.endswith('.' + entity):
            _LOGGER.warning(
                f'CSR without ".entity" in its common_name: '
                f'{common_name_prefix}'
            )
            raise ValueError(
                f'CSR without ".{entity}" in its common_name: '
                f'{common_name_prefix}'
            )

        value = common_name_prefix[:-1 * len('.' + entity)]

        try:
            identifier = UUID(value)
        except ValueError:
            _LOGGER.warning(f'Invalid identifier: {value}')
            raise ValueError(
                f'Invalid identifier: {value}'
            )

        return entity, identifier


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
        )

        self.ca = True

        self.csrs_accepted_for = 'service-issuing'

    def create_csr(self):
        '''
        Creates an RSA private key and X.509 cert signed by the network root CA

        :returns: csr
        :raises: ValueError if the Secret instance already has a
                            private key or cert
        '''

        common_name = 'services-ca.{self.network}'

        return super().create_csr(common_name, key_size=4096, ca=self.ca)

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

        common_name_prefix = super().review_csr(csr)

        entity = 'service'
        if not common_name_prefix.endswith('.' + entity):
            _LOGGER.warning(
                f'CSR without ".{entity}" in its common_name: '
                f'{common_name_prefix}'
            )
            raise ValueError(
                f'CSR without ".{entity}" in its common_name: '
                f'{common_name_prefix}'
            )

        if not common_name_prefix.startswith('ca-'):
            _LOGGER.warning(
                f'Service CA common name %s does not start with '
                f'"ca-{common_name_prefix}"'
            )
            raise ValueError(
                f'Service CA common name {common_name_prefix} does not start '
                f'with "ca-"'
            )

        identifier = common_name_prefix[3:-1 * len('.' + entity)]

        if not identifier.isdigit():
            _LOGGER.warning(
                f'Service dentifier must be all-digits: {identifier}'
            )
            raise ValueError(
                f'Service dentifier must be all-digits: {identifier}'
            )

        return entity, identifier
