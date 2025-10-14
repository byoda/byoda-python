'''
Cert manipulation

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from datetime import datetime
from logging import Logger
from logging import getLogger

from cryptography.x509 import Certificate
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes

from byoda.storage import FileStorage

_LOGGER: Logger = getLogger(__name__)


class CertChain:
    __slots__: list[str] = [
        'signed_cert', 'cert_chain'
    ]

    def __init__(self, signed_cert: Certificate,
                 cert_chain: list[Certificate]) -> None:
        '''
        Represents a signed cert and the list of certs of issuing CAs
        that signed the cert. Does not include the root cert. This class
        works with X.509 cert(chains), not with the Secret class and the
        classes derived from it.

        :param X509 signed_cert : the signed cert
        :param list cert_chain  : the list of certs in the cert chain,
        excluding the signed cert
        :returns: (none)
        :raises: (none)
        '''

        self.signed_cert: Certificate = signed_cert
        self.cert_chain: list[Certificate] = cert_chain

    def __str__(self) -> str:
        '''
        :returns: the certchain as a string
        '''

        data: str = self.cert_as_string() + self.cert_chain_as_string()
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
        data: str = ''
        for cert in self.cert_chain:
            data += self.cert_as_string(cert)

        return data

    def cert_as_string(self, cert: Certificate = None) -> str:
        if not cert:
            cert = self.signed_cert

        not_valid_before: datetime = cert.not_valid_before_utc
        not_valid_after: datetime = cert.not_valid_after_utc
        cert_info: str = (
            f'# Issuer {cert.issuer}\n'
            f'# Subject {cert.subject}\n'
            f'# Valid from {not_valid_before} to {not_valid_after}\n'
        )
        data: str = cert_info
        data += cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')
        data += '\n'

        return data

    async def save(self, filepath, storage_driver: FileStorage,
                   with_fingerprint: bool = True) -> None:
        '''
        Saves the cert chain to a file
        '''

        await storage_driver.write(filepath, str(self))

        if with_fingerprint:
            fingerprint: str = self.signed_cert.fingerprint(hashes.SHA256()).hex()
            await storage_driver.write(f'{filepath}-{fingerprint}', str(self))
