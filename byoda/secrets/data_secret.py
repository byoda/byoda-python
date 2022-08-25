'''
Cert manipulation

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import logging

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.fernet import Fernet

from byoda.storage.filestorage import FileStorage

from byoda.util.api_client.api_client import ApiClient, HttpMethod

from .secret import Secret

_LOGGER = logging.getLogger(__name__)

_BYODA_DIR = '/.byoda/'
_ROOT_DIR = os.environ['HOME'] + _BYODA_DIR


class DataSecret(Secret):
    '''
    Interface class for the PKI secrets used for:
    - signing and verification of the signature of documents
    - encrypting and decrypting documents

    Properties:
    - cert                 : instance of cryptography.x509
    - key                  : instance of
                             cryptography.hazmat.primitives.asymmetric.rsa
    - password             : string protecting the private key
    - shared_key           : unprotected shared secret used by Fernet
    - protected_shared_key : protected shared secret used by Fernet
    - fernet               : instance of cryptography.fernet.Fernet
    '''

    def __init__(self, cert_file: str = None, key_file: str = None,
                 storage_driver: FileStorage = None):

        super().__init__(cert_file, key_file, storage_driver)

        # the key to use for Fernet encryption/decryption
        self.shared_key = None

        # The shared key encrypted with the private key of
        # this secret
        self.protected_shared_key = None

        self.fernet = None

    def encrypt(self, data: bytes):
        '''
        Encrypts the provided data with the Fernet algorithm

        :param bytes data : data to be encrypted
        :returns: encrypted data
        :raises: KeyError if no shared secret was generated or
                            loaded for this instance of Secret
        '''

        if not self.shared_key:
            raise KeyError('No shared secret available to encrypt')

        if isinstance(data, str):
            data = str.encode(data)

        _LOGGER.debug('Encrypting data with %d bytes', len(data))
        ciphertext = self.fernet.encrypt(data)
        return ciphertext

    def decrypt(self, ciphertext: bytes) -> bytes:
        '''
        Decrypts the ciphertext

        :param ciphertext : data to be encrypted
        :returns: encrypted data
        :raises: KeyError if no shared secret was generated
                                  or loaded for this instance of Secret
        '''

        if not self.shared_key:
            raise KeyError('No shared secret available to decrypt')

        data = self.fernet.decrypt(ciphertext)
        _LOGGER.debug('Decrypted data with %d bytes', len(data))

        return data

    def create_shared_key(self, target_secret=None):
        '''
        Creates an encrypted shared key

        :param Secret target_secret : the target X.509 cert that should be
                                      able to decrypt the shared key
        :returns: (none)
        :raises: (none)
        '''

        if not target_secret:
            target_secret = self

        _LOGGER.debug(
            f'Creating a shared key protected with cert '
            f'{target_secret.common_name}'
        )

        if self.shared_key:
            _LOGGER.debug('Replacing existing shared key')

        self.shared_key = Fernet.generate_key()

        public_key = target_secret.cert.public_key()
        self.protected_shared_key = public_key.encrypt(
            self.shared_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        _LOGGER.debug('Initializing new Fernet instance')
        self.fernet = Fernet(self.shared_key)

    def load_shared_key(self, protected_shared_key: bytes):
        '''
        Loads a protected shared key

        :param protected_shared_key : the protected shared key
        :returns: (none)
        :raises: (none)
        '''

        _LOGGER.debug(
            f'Decrypting protected shared key with cert {self.common_name}'
        )

        self.protected_shared_key = protected_shared_key
        self.shared_key = self.private_key.decrypt(
            self.protected_shared_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        _LOGGER.debug(
            'Initializing new Fernet instance from decrypted shared secret'
        )
        self.fernet = Fernet(self.shared_key)

    async def download(self, url: str):
        '''
        Downloads the data secret of a remote member

        :returns MemberSecret : the downloaded data secret
        :raises: (none)
        '''

        _LOGGER.debug(f'Downloading data secret from {url}')
        resp = await ApiClient.call(url, HttpMethod.GET)

        if resp.status == 200:
            cert_data = await resp.text()
            return cert_data
        else:
            raise RuntimeError(f'Could not download data secret via {url}')
