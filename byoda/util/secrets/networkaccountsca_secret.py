'''
Cert manipulation of network secrets: root CA, accounts CA and services CA

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID

from byoda.util import Paths

from byoda.datatypes import IdType, EntityId

from . import Secret, CSR

_LOGGER = logging.getLogger(__name__)


class NetworkAccountsCaSecret(Secret):
    def __init__(self, paths: Paths = None, network=None):
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

        if paths:
            self.network = paths.network
            super().__init__(
                cert_file=paths.get(Paths.NETWORK_ACCOUNTS_CA_CERT_FILE),
                key_file=paths.get(Paths.NETWORK_ACCOUNTS_CA_KEY_FILE),
                storage_driver=paths.storage_driver,
            ),
        else:
            super().__init__(storage_driver=paths.storage_driver)
            self.network = network

        self.ca = True
        self.id_type = IdType.ACCOUNTS_CA

        self.csrs_accepted_for = ('account')

    def create_csr(self) -> CSR:
        '''
        Creates an RSA private key and X.509 cert signature request

        :returns: csr
        :raises: ValueError if the Secret instance already has a cert or a
                 private key

        '''

        commonname = f'{self.id_type.value}.{self.network}'

        return super().create_csr(commonname, key_size=4096, ca=self.ca)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an AccountSecret. If so, it sets the 'account_id' property of the
        instance to the UUID parsed from the commonname

        :param commonname: the commonname to check
        :returns: account entity
        :raises: ValueError if the commonname is not valid for certs signed
        by instances of this class
        '''

        # Checks on commonname type and the network postfix
        commonname_prefix = super().review_commonname(commonname)

        bits = commonname_prefix.split('.')
        if len(bits) != 2:
            raise ValueError(
                f'Invalid common name structure {commonname_prefix}'
            )

        (account_id, subdomain) = bits
        try:
            account_id = UUID(account_id)
        except ValueError:
            raise ValueError(
                f'Commmonname {commonname_prefix} does not start with a UUID'
            )

        if IdType(subdomain) != IdType.ACCOUNT:
            raise ValueError(
                f'commonname {commonname} has incorrect subdomain'
            )

        return EntityId(IdType.ACCOUNT, account_id, None)

    def review_csr(self, csr: CSR) -> EntityId:
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

        commonname = super().review_csr(csr)

        entity_id = self.review_commonname(commonname)

        return entity_id
