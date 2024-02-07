'''
Cert manipulation

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import struct

from copy import copy
from typing import Self
from typing import TypeVar
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import utils
from cryptography.fernet import Fernet

# Imports that enable code to import from this module
from cryptography.exceptions import InvalidSignature        # noqa: F401

from byoda.storage.filestorage import FileStorage

from byoda.util.paths import Paths

from byoda import config

from byoda.util.logger import Logger

from .secret import Secret

Server = TypeVar('Server')

_LOGGER: Logger = getLogger(__name__)

# This is not a limit to the data getting signed or verified, but
# a limit to the amount of data fed to the hasher at each iteration
_RSA_SIGN_MAX_MESSAGE_LENGTH = 1024


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

    __slots__: list[str] = [
        'shared_key', 'protected_shared_key', 'fernet'
    ]

    # When should the secret be renewed
    RENEW_WANTED: datetime = datetime.now(tz=UTC) + timedelta(days=180)
    RENEW_NEEDED: datetime = datetime.now(tz=UTC) + timedelta(days=30)

    def __init__(self, cert_file: str = None, key_file: str = None,
                 storage_driver: FileStorage = None) -> None:

        super().__init__(cert_file, key_file, storage_driver)

        # the key to use for Fernet encryption/decryption
        self.shared_key: bytes = None

        # The shared key encrypted with the private key of
        # this secret
        self.protected_shared_key: bytes = None

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

        ciphertext: bytes = self.fernet.encrypt(data)
        return ciphertext

    def encrypt_file(self, file_in: str, file_out: str,
                     block_size: int = 1 << 16 - 4) -> None:
        '''
        Encrypts a file without Fernet needing to have the whole file in memory
        '''

        # based on https://stackoverflow.com/questions/69312922/how-to-encrypt-large-file-using-python      # noqa: E501
        with open(file_in, 'rb') as fd_in, open(file_out, 'wb') as fd_out:
            while True:
                chunk: bytes = fd_in.read(block_size)
                if len(chunk) == 0:
                    break
                encrypted: bytes = self.encrypt(chunk, with_logging=False)
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

        data: bytes = self.fernet.decrypt(ciphertext)
        if with_logging:
            _LOGGER.debug('Decrypted data with %d bytes', len(data))

        return data

    def decrypt_file(self, file_in: str, file_out: str) -> None:
        '''
        Decrypts a file without Fernet needing to have the whole file in memory
        '''

        # based on https://stackoverflow.com/questions/69312922/how-to-encrypt-large-file-using-python      # noqa: E501
        with open(file_in, 'rb') as fd_in, open(file_out, 'wb') as fd_out:
            while True:
                size_data: bytes = fd_in.read(4)
                if len(size_data) == 0:
                    break
                chunk: bytes = fd_in.read(struct.unpack('<I', size_data)[0])
                decrypted: bytes = self.decrypt(chunk, with_logging=False)
                fd_out.write(decrypted)

        _LOGGER.debug(f'Decrypted {file_in} to {file_out}')

    def create_shared_key(self, target_secret=None) -> None:
        '''
        Creates an encrypted shared key

        :param Secret target_secret : the target X.509 cert that should be
                                      able to decrypt the shared key
        :returns: (none)
        :raises: (none)
        '''

        if not target_secret:
            target_secret: Self = self

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

    def load_shared_key(self, protected_shared_key: bytes) -> None:
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

    def sign_message(self, message: str, hash_algorithm: str = 'SHA256'
                     ) -> bytes:
        '''
        Sign a message

        :returns: signature for the message
        :raises: ValueError, NotImplementedError
        '''

        if isinstance(message, str):
            message = message.encode('utf-8')
        elif not isinstance(message, bytes):
            raise ValueError(
                f'Message must be of type string or bytes, not {type(message)}'
            )

        fingerprint: str = self.fingerprint().hex()

        _LOGGER.debug(
            f'Creating signature with cert with fingerprint {fingerprint}'
        )

        chosen_hash = hashes.SHA256()

        digest: bytes = DataSecret._get_digest(message, chosen_hash)

        signature: bytes = self.private_key.sign(
            digest,
            padding.PSS(
                mgf=padding.MGF1(chosen_hash),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            utils.Prehashed(chosen_hash)
        )

        return signature

    def verify_message_signature(self, message: str, signature: bytes,
                                 hash_algorithm: str = 'SHA256') -> None:
        '''
        Verify the signature for a message

        :raises: InvalidSignature if the signature is invalid, ValueError
                 if the input is invalid
        '''

        if isinstance(message, str):
            message = message.encode('utf-8')
        elif not isinstance(message, bytes):
            raise ValueError(
                f'Message must be of type string or bytes, not {type(message)}'
            )

        if hash_algorithm == 'SHA256':
            chosen_hash = hashes.SHA256()
        else:
            raise NotImplementedError(
                'Only SHA256 is supported as hash algorithm'
            )

        fingerprint: str = self.fingerprint().hex()
        _LOGGER.debug(
            f'Verifying signature with cert with fingerprint {fingerprint}'
        )

        digest: bytes = DataSecret._get_digest(message, chosen_hash)

        self.cert.public_key().verify(
            signature,
            digest,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            utils.Prehashed(chosen_hash)
        )

    @staticmethod
    def _get_digest(message: bytes, chosen_hash: hashes) -> bytes:
        '''
        Generates a digest hash for any length of message
        '''

        hasher = hashes.Hash(chosen_hash)
        message = copy(message)
        while message:
            if len(message) > _RSA_SIGN_MAX_MESSAGE_LENGTH:
                hasher.update(message[:_RSA_SIGN_MAX_MESSAGE_LENGTH])
                message = message[_RSA_SIGN_MAX_MESSAGE_LENGTH:]
            else:
                hasher.update(message)
                message = None
        digest: bytes = hasher.finalize()

        _LOGGER.debug(f'Generated digest: {digest.hex()}')

        return digest

    async def download(self, url: str, ca_filepath: str = None,
                       network_name: str | None = None) -> str | None:
        '''
        Downloads the data secret of a remote member

        :returns MemberSecret : the downloaded data secret as a string
        :raises: (none)
        '''

        if not ca_filepath:
            server: Server = config.server
            paths: Paths = server.paths
            ca_filepath = (
                paths.storage_driver.local_path +
                paths.get(Paths.NETWORK_ROOT_CA_CERT_FILE)
            )

        _LOGGER.debug(f'Downloading data secret from {url}')
        cert_data: str | None = await Secret.download(
            url, root_ca_filepath=ca_filepath, network_name=network_name
        )

        return cert_data
