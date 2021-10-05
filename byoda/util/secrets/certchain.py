'''
Cert manipulation

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import List

from cryptography.x509 import Certificate
from cryptography.hazmat.primitives import serialization

_LOGGER = logging.getLogger(__name__)


class CertChain:
    def __init__(self, signed_cert: Certificate, cert_chain: List[Certificate]
                 ):
        '''
        Represents a signed cert and the list of certs of issuing CAs
        that signed the cert. Does not include the root cert.

        :param X509 signed_cert : the signed cert
        :param list cert_chain  : the list of certs in the cert chain,
        excluding the signed cert
        :returns: (none)
        :raises: (none)
        '''

        self.signed_cert: Certificate = signed_cert
        self.cert_chain: List[Certificate] = cert_chain

    def __str__(self) -> str:
        '''
        :returns: the certchain as a bytes array
        '''

        data = self.cert_as_string() + self.cert_chain_as_string()
        return data

    def as_dict(self) -> dict:
        '''

        :returns: {'cert': cert, 'certchain': certchain}
        '''
        return {
            'signed_cert': self.cert_as_string(),
            'cert_chain': self.cert_chain_as_string()
        }

    def cert_chain_as_string(self) -> str:
        data = ''
        for cert in self.cert_chain:
            data += self.cert_as_string(cert)

        return data

    def cert_as_string(self, cert: Certificate = None) -> str:
        if not cert:
            cert = self.signed_cert

        cert_info = (
            f'# Issuer {cert.issuer}\n'
            f'# Subject {cert.subject}\n'
            f'# Valid from {cert.not_valid_before} to {cert.not_valid_after}\n'
        )
        data = cert_info
        data += cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')
        data += '\n'

        return data
