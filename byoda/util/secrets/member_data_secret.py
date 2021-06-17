'''
Cert manipulation for data of an account

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging


from byoda.util import Paths

from byoda.datatypes import IdType, CsrSource
from . import Secret, CSR

_LOGGER = logging.getLogger(__name__)


class MemberDataSecret(Secret):
    def __init__(self, paths: Paths):
        '''
        Class for the member-data secret. This secret is used to encrypt
        data of an account for a service.
        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :returns: ValueError if both 'paths' and 'network' parameters are
        specified
        :raises: (none)
        '''

        self.account_id = paths.account_id
        super().__init__(
            cert_file=paths.get(Paths.ACCOUNT_DATA_CERT_FILE),
            key_file=paths.get(Paths.ACCOUNT_DATA_KEY_FILE),
            storage_driver=paths.storage_driver
        )
        self.account_alias = paths.account
        self.network = paths.network
        self.ca = False
        self.issuing_ca = None
        self.id_type = IdType.MEMBER_DATA

        self.csrs_accepted_for = ()

    def create(self, expire: int = 109500):
        '''
        Creates an RSA private key and X.509 cert

        :param int expire: days after which the cert should expire
        :returns: (none)
        :raises: ValueError if the Secret instance already
                            has a private key or cert

        '''

        common_name = f'{self.account_id}.accout_data.{self.network}'
        super().create(common_name, expire=expire, key_size=4096, ca=self.ca)

    def create_csr(self):
        raise NotImplementedError

    def review_commonname(self, commonname: str) -> str:
        '''
        Checks if the structure of common name matches with a common name an
        account_data

        :param commonname: the commonname to check
        :returns: the common name with the network domain stripped off
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        commonname_prefix = super().review_commonname(commonname)

        if commonname_prefix not in self.csrs_accepted_for:
            raise ValueError('An Account Data secret does not sign CSRs')

        return commonname_prefix

    def review_csr(self, csr: CSR, source: CsrSource = CsrSource.WEBAPI
                   ) -> str:
        '''
        Review a CSR. CSRs from NetworkAccountCA and NetworkServicesCA are
        permissable.

        :param csr: cryptography.X509.CertificateSigningRequest
        :param source: source of the CSR
        :returns: 'accounts-ca' or 'services-ca'
        :raises: ValueError if this object is not a CA because it only has
        access to the cert and not the private_key) or if the CommonName is
        not valid in the CSR for signature by this CA
        '''

        raise NotImplementedError
