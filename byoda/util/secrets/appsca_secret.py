'''
Cert manipulation for service secrets: Apps CA

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID
from typing import TypeVar

from cryptography.x509 import CertificateSigningRequest

from byoda.util import Paths

from byoda.datatypes import IdType, CsrSource, EntityId
from . import Secret, CSR

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class AppsCaSecret(Secret):
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

        paths = network.paths
        self.network = network.network
        self.service_id = int(service_id)
        self.service = service

        super().__init__(
            cert_file=paths.get(
                Paths.SERVICE_APPS_CA_CERT_FILE, service_id=service_id
            ),
            key_file=paths.get(
                Paths.SERVICE_APPS_CA_KEY_FILE, service_id=service_id
            ),
            storage_driver=paths.storage_driver
        )
        self.ca = True
        self.id_type = IdType.APPS_CA

        self.csrs_accepted_for = ('member')

    def create_csr(self, service_id: int) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param service_id: identifier for the service
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        common_name = (
            f'{self.id_type.value}{service_id}.{IdType.SERVICE.value}.'
            f'{self.network}'
        )

        return super().create_csr(common_name, key_size=4096, ca=True)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an Appsecret. If so, it sets the 'account_id' property of the
        instance to the UUID parsed from the commonname

        :param commonname: the commonname to check
        :returns: entity parsed from the commonname
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        commonname_prefix = super().review_commonname(commonname)

        bits = commonname_prefix.split('.')
        if len(bits) != 2:
            raise ValueError(f'Invalid number of domain levels: {commonname}')

        value, subdomain = bits
        try:
            id_type = IdType(subdomain)
        except ValueError:
            raise ValueError(f'{commonname_prefix} has an invalid subdomain')

        if id_type != IdType.MEMBER:
            raise ValueError(f'commonname {commonname} is not for a member')

        # Now we're left with {member_id:UUID}_{service_id:int}
        divider = value.rfind('_')
        if not divider:
            raise ValueError(
                'No underscore in prefix in commonname {commonname_prefix}'
            )

        identifier, service_id = value.split('_')
        try:
            self.member_id = UUID(identifier)
        except ValueError:
            raise ValueError(f'{identifier} does not have a valid MemberID')

        try:
            self.service_id = int(service_id)
        except ValueError:
            raise ValueError(f'{identifier} does not have a valid ServiceID')

        return EntityId(IdType.MEMBER, self.member_id, self.service_id)

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
