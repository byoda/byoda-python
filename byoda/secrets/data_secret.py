'''
Cert manipulation

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import struct
import logging
from datetime import datetime, timedelta

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

    # When should the secret be renewed
    RENEW_WANTED: datetime = datetime.now() + timedelta(days=180)
    RENEW_NEEDED: datetime = datetime.now() + timedelta(days=30)

    def __init__(self, cert_file: str = None, key_file: str = None,
                 storage_driver: FileStorage = None):

        super().__init__(cert_file, key_file, storage_driver)

        # the key to use for Fernet encryption/decryption
        self.shared_key = None

        # The shared key encrypted with the private key of
        # this secret
        self.protected_shared_key = None

        self.fernet = None

    def encrypt(self, data: bytes, with_logging: bool = True) -> bytes:
        '''
        Encrypts the provided data with the Fernet algorithm

        :param bytes data : data to be encrypted
        :param with_logging: write debug logging, for use by encrypt_file()
        :returns: encrypted data
        :raises: KeyError if no shared secret was generated or
                            loaded for this instance of Secret
        '''

        if not self.shared_key:
            raise KeyError('No shared secret available to encrypt')

        if isinstance(data, str):
            data = str.encode(data)

        if with_logging:
            _LOGGER.debug('Encrypting data with %d bytes', len(data))

        ciphertext = self.fernet.encrypt(data)
        return ciphertext

    def encrypt_file(self, file_in: str, file_out: str,
                     block_size: int = 1 << 16 - 4):
        '''
        Encrypts a file without Fernet needing to have the whole file in memory
        '''

        # based on https://stackoverflow.com/questions/69312922/how-to-encrypt-large-file-using-python      # noqa: E501
        with open(file_in, 'rb') as fd_in, open(file_out, 'wb') as fd_out:
            while True:
                chunk = fd_in.read(block_size)
                if len(chunk) == 0:
                    break
                encrypted = self.encrypt(chunk, with_logging=False)
                fd_out.write(struct.pack('<I', len(encrypted)))
                fd_out.write(encrypted)
                if len(chunk) < block_size:
                    break

        _LOGGER.debug(f'Encrypted {file_in} to {file_out}')

    def decrypt(self, ciphertext: bytes, with_logging=True) -> bytes:
        '''
        Decrypts the ciphertext

        :param ciphertext: data to be encrypted
        :param with_logging: write debug logging, for use by decrypt_file()
        :returns: encrypted data
        :raises: KeyError if no shared secret was generated
                                  or loaded for this instance of Secret
        '''

        if not self.shared_key:
            raise KeyError('No shared secret available to decrypt')

        data = self.fernet.decrypt(ciphertext)
        if with_logging:
            _LOGGER.debug('Decrypted data with %d bytes', len(data))

        return data

    def decrypt_file(self, file_in: str, file_out: str):
        '''
        Decrypts a file without Fernet needing to have the whole file in memory
        '''

        # based on https://stackoverflow.com/questions/69312922/how-to-encrypt-large-file-using-python      # noqa: E501
        with open(file_in, 'rb') as fd_in, open(file_out, 'wb') as fd_out:
            while True:
                size_data = fd_in.read(4)
                if len(size_data) == 0:
                    break
                chunk = fd_in.read(struct.unpack('<I', size_data)[0])
                decrypted = self.decrypt(chunk, with_logging=False)
                fd_out.write(decrypted)

        _LOGGER.debug(f'Decrypted {file_in} to {file_out}')

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

    async def download(self, url: str) -> str | None:
        '''
        Downloads the data secret of a remote member

        :returns MemberSecret : the downloaded data secret as a string
        :raises: (none)
        '''

        _LOGGER.debug(f'Downloading data secret from {url}')
        resp = await ApiClient.call(url, HttpMethod.GET)

        if resp.status == 200:
            cert_data = await resp.text()
            return cert_data
        else:
            return None
