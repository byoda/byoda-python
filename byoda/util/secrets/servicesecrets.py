'''
Cert manipulation for service secrets: Service CA, Service Members CA and
Service secret

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID

from byoda.util import Paths

from . import Secret, CsrSource

_LOGGER = logging.getLogger(__name__)


class ServiceCaSecret(Secret):
    def __init__(self, service_alias, paths):
        '''
        Class for the service issuing CA

        :param str service_alias : short name for the service
        :param Paths paths       : instance of Paths class defining the
                                   directory structure and file names of a
                                   BYODA network disk
        :returns: (none)
        :raises: (none)
        '''

        self.network = paths.network
        self.service = service_alias

        super().__init__(
            cert_file=paths.get(
                Paths.SERVICE_CA_CERT_FILE, service_alias=service_alias
            ),
            key_file=paths.get(
                Paths.SERVICE_CA_KEY_FILE, service_alias=service_alias
            )
        )
        self.ca = True

        self.csrs_accepted_for = ('members-ca')

    def create_csr(self, service_id):
        '''
        Creates an RSA private key and X.509 CSR the the Service issuing CA

        :param int service_id : identifier for the service
        :param int expire     : days after which the cert should expire
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        common_name = f'ca-{service_id}.service.{self.network}'

        return super().create_csr(common_name, key_size=4096, ca=self.ca)

    def review_csr(self, csr, source=CsrSource.WEBAPI):
        '''
        Review a CSR. CSRs for register a service or or service_member_ca
        are permissable. Note that this function does not check whether the
        service identifier is already in use

        :param X509 csr         : cryptography.X509.CertificateSigningRequest
        :param CsrSource source : source of the CSR
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

        if source == CsrSource.WEBAPI:
            _LOGGER.warning(
                'This CA does not accept CSRs received via API call'
            )
            raise ValueError(
                'This CA does not accept CSRs received via API call'
            )

        # There are two types of CSRs for this CA:
        # the CSR for the service certificate
        # the CSR for the members-ca for the service.
        # They are formatted '(members-ca-)?(service_id).(network)
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

        if common_name_prefix.startswith('members-ca-'):
            entity = 'members-ca'
            common_name_prefix = common_name_prefix[len('members-ca-'):]

        identifier = common_name_prefix[:-1 * len('.' + entity)]

        if not identifier.isdigit():
            _LOGGER.warning(
                'Service ID in common name prefix must only contain digits: '
                f'{identifier}',
            )
            raise ValueError(
                'Service ID in common name prefix must only contain digits: '
                f'{identifier}'
            )

        return entity, identifier


class MembersCaSecret(Secret):
    def __init__(self, service_alias, paths):
        '''
        Class for the service members CA secret

        :param str service_alias : short name for the service
        :param Paths paths       : instance of Paths class defining the
                                   directory
                                   structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.network = paths.network
        self.service = paths.service

        super().__init__(
            cert_file=paths.get(
                Paths.SERVICE_MEMBERS_CA_CERT_FILE, service_alias=service_alias
            ),
            key_file=paths.get(
                Paths.SERVICE_MEMBERS_CA_KEY_FILE, service_alias=service_alias
            ),
        )
        self.ca = True

        self.csrs_accepted_for = ('member')

    def create_csr(self, service_id):
        '''
        Creates an RSA private key and X.509 CSR

        :param int service_id: identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        common_name = f'members-ca-{service_id}.service.{self.network}'

        return super().create_csr(common_name, key_size=4096, ca=True)

    def review_csr(self, csr):
        '''
        Review a CSR. CSRs for registering service member are permissable.

        :param X509 csr: cryptography.X509.CertificateSigningRequest
        :returns: entity, identifier
        :raises: ValueError if this object is not a CA (because it only has
                 access to the cert and not the private_key) or if the
                 CommonName in the CSR is not valid for signature by this CA
        '''
        if not self.private_key_file:
            _LOGGER.exception('CSR received while we are not a CA')
            raise ValueError('CSR received while we are not a CA')

        # CN in CSR: '{member_id}-{service_id}.member.{network}
        common_name_prefix = super().review_csr(csr)

        entity = 'member'
        if not common_name_prefix.endswith('.' + entity):
            _LOGGER.warning(
                f'CSR without ".{entity}" in its common_name: '
                f'{common_name_prefix}'
            )
            raise ValueError(
                f'CSR without ".{entity}" in its common_name: '
                f'{common_name_prefix}'
            )

        value = common_name_prefix[:-1 * len('.' + entity)]

        # Now we're left with {member_id:UUID}-{service_id:int}
        divider = value.rfind('-')
        if not divider:
            _LOGGER.warning(
                'No dash in common name prefix: {common_name_prefix}'
            )
            raise ValueError(
                'No dash in common name prefix {common_name_prefix}'
            )

        service_id = value[divider + 1:]
        if not service_id.isdigit():
            _LOGGER.warning(
                'Service ID in common name prefix must only contain digits: '
                f'{service_id}',
            )
            raise ValueError(
                'Service ID in common name prefix must only contain digits: '
                f'{service_id}'
            )

        value = value[:divider]
        try:
            identifier = UUID(value)
        except ValueError:
            _LOGGER.warning(f'Invalid identifier: {value} for entity {entity}')
            raise ValueError(
                f'Invalid identifier: {value} for entity {entity}'
            )

        return entity, identifier


class ServiceSecret(Secret):
    def __init__(self, service_alias, paths):
        '''
        Class for the service secret

        :param str service_alias : short name for the service
        :param Paths paths       : instance of Paths class defining the
                                   directory, structure and file names of a
                                   BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.network = paths.network
        self.service = service_alias

        super().__init__(
            cert_file=paths.get(
                Paths.SERVICE_CERT_FILE, service_alias=service_alias
            ),
            key_file=paths.get(
                Paths.SERVICE_KEY_FILE, service_alias=service_alias
            )
        )
        self.ca = False

    def create_csr(self, service_id):
        '''
        Creates an RSA private key and X.509 CSR

        :param int service_id : identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        common_name = f'{service_id}.service.{self.network}'

        return super().create_csr(common_name, ca=self.ca)

    def review_csr(self, csr, source=CsrSource.WEBAPI):
        raise NotImplementedError
