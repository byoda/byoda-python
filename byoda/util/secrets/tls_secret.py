'''
Cert manipulation for TLS cert/key

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from cryptography.x509 import CertificateSigningRequest as CSR

from byoda.util import Paths

from byoda.datatypes import IdType

from . import Secret
# from .acmeclient import ACMEClient

_LOGGER = logging.getLogger(__name__)


class TlsSecret(Secret):
    def __init__(self, paths: Paths, fqdn: str):
        '''
        Class for the network Account secret

        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :param fqdn: the FQDN for the common_name for the secret
        :returns: (none)
        :raises: (none)
        '''

        super().__init__(
            cert_file=paths.get(Paths.TLS_CERT_FILE),
            key_file=paths.get(Paths.TLS_KEY_FILE),
            storage_driver=paths.storage_driver
        )

        self.fqdn = fqdn
        self.ca = False
        self.id_type = IdType.TLS

    def create_csr(self) -> CSR:
        '''
        Creates an RSA private key and X.509 CSR

        :returns: certificate signing request
        :raises: ValueError if the Secret instance already has a private key
        or cert
        '''

        return super().create_csr(self.fqdn, ca=self.ca)

    def get_csr_signature(self, csr: CSR):
        '''
        Requests a signed cert from the LetsEncrypt CA.

        :param csr: the certificate signing request
        :returns: (none)
        '''

        # acme = ACMEClient(self, csr)
