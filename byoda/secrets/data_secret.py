'''
Cert manipulation

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import base64
import binascii
import json
import os
import struct

from copy import copy
from typing import Self
from typing import TypeVar
from typing import override
from logging import Logger
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from cryptography import x509
from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Imports that enable code to import from this module
from cryptography.exceptions import InvalidSignature        # noqa: F401

from byoda.storage.filestorage import FileStorage

from byoda.util.paths import Paths

from byoda import config

from .secret import Secret
from .ca_secret import CaSecret

Server = TypeVar('Server')

_LOGGER: Logger = getLogger(__name__)

_KEY_ENVELOPE_MAGIC: bytes = b'BYODA-DATA-KEY-v1\n'
_KEY_ENVELOPE_ALGORITHM: str = 'ECDH-P256-HKDF-SHA256-AESGCM'
_KEY_ENVELOPE_CURVE: str = 'secp256r1'
_KEY_ENVELOPE_INFO: bytes = b'byoda data secret protected shared key v1'
_KEY_ENVELOPE_SALT_LENGTH: int = 32
_KEY_ENVELOPE_NONCE_LENGTH: int = 12
_KEY_ENVELOPE_KEY_LENGTH: int = 32

# This is not a limit to the data getting signed or verified, but
# a limit to the amount of data fed to the hasher at each iteration
_SIGN_MAX_MESSAGE_LENGTH = 1024


class DataSecret(Secret):
    '''
    Interface class for the PKI secrets used for:
    - signing and verification of the signature of documents
    - encrypting and decrypting documents

    Properties:
    - cert                 : instance of cryptography.x509
    - key                  : instance of
                             cryptography.hazmat.primitives.asymmetric.ec
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

    _KEY_USAGE_CONSTRAINTS: dict[str, bool] = {
                'digital_signature': True,
                'content_commitment': True,
                'key_encipherment': False,
                'data_encipherment': False,
                'key_agreement': True,
                'key_cert_sign': False,
                'crl_sign': False,
                'encipher_only': False,
                'decipher_only': False,
    }

    _EXTENDED_KEY_USAGE: list[x509.ObjectIdentifier] = [
        # x509.ExtendedKeyUsageOID.SERVER_AUTH,
        # x509.ExtendedKeyUsageOID.CLIENT_AUTH,
        x509.ExtendedKeyUsageOID.CODE_SIGNING,
        x509.ExtendedKeyUsageOID.EMAIL_PROTECTION,
        # x509.ExtendedKeyUsageOID.TIME_STAMPING,
        # x509.ExtendedKeyUsageOID.OCSP_SIGNING,
        # x509.ExtendedKeyUsageOID.SMARTCARD_LOGON,
        # x509.ExtendedKeyUsageOID.KERBEROS_PKINIT_KDC,
        # x509.ExtendedKeyUsageOID.IPSEC_IKE,
        # x509.ExtendedKeyUsageOID.CERTIFICATE_TRANSPARENCY,
    ]

    @override
    def __init__(self, cert_file: str = None, key_file: str = None,
                 storage_driver: FileStorage = None) -> None:

        super().__init__(cert_file, key_file, storage_driver)

        # the key to use for Fernet encryption/decryption
        self.shared_key: bytes | None = None

        # The shared key encrypted for this secret's certificate
        self.protected_shared_key: bytes | None = None

        self.key_usage_constraints: dict[str, bool] = \
            DataSecret._KEY_USAGE_CONSTRAINTS
        self.extended_key_usage: list[x509.ObjectIdentifier] = \
            DataSecret._EXTENDED_KEY_USAGE
        self.fernet = None

    def generate_private_key(self) -> ec.EllipticCurvePrivateKey:
        _LOGGER.debug('Generating EC private key for a data secret')
        return ec.generate_private_key(ec.SECP256R1())

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
                if len(size_data) != 4:
                    raise ValueError(
                        'Protected file has truncated chunk-size header'
                    )

                chunk_size: int = struct.unpack('<I', size_data)[0]
                chunk: bytes = fd_in.read(chunk_size)
                if len(chunk) != chunk_size:
                    raise ValueError('Protected file has truncated chunk')

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
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            raise TypeError(
                'Data secret certificates must use EC public keys'
            )

        self.protected_shared_key = self._protect_shared_key(
            public_key, self.shared_key
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
        self.shared_key = self._unprotect_shared_key(protected_shared_key)
        _LOGGER.debug(
            'Initializing new Fernet instance from decrypted shared secret'
        )
        self.fernet = Fernet(self.shared_key)

    @staticmethod
    def _b64encode(data: bytes) -> str:
        return base64.b64encode(data).decode('ascii')

    @staticmethod
    def _b64decode(envelope: dict[str, str], key: str) -> bytes:
        value: str | None = envelope.get(key)
        if not isinstance(value, str):
            raise ValueError(f'Protected shared key is missing {key}')

        try:
            return base64.b64decode(value.encode('ascii'), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                f'Protected shared key has invalid {key}'
            ) from exc

    @staticmethod
    def _derive_wrapping_key(
        private_key: ec.EllipticCurvePrivateKey,
        public_key: ec.EllipticCurvePublicKey,
        salt: bytes,
    ) -> bytes:
        shared_secret: bytes = private_key.exchange(ec.ECDH(), public_key)
        return HKDF(
            algorithm=hashes.SHA256(),
            length=_KEY_ENVELOPE_KEY_LENGTH,
            salt=salt,
            info=_KEY_ENVELOPE_INFO,
        ).derive(shared_secret)

    @staticmethod
    def _protect_shared_key(
        public_key: ec.EllipticCurvePublicKey, shared_key: bytes
    ) -> bytes:
        ephemeral_key: ec.EllipticCurvePrivateKey = ec.generate_private_key(
            ec.SECP256R1()
        )
        salt: bytes = os.urandom(_KEY_ENVELOPE_SALT_LENGTH)
        nonce: bytes = os.urandom(_KEY_ENVELOPE_NONCE_LENGTH)
        wrapping_key: bytes = DataSecret._derive_wrapping_key(
            ephemeral_key, public_key, salt
        )
        ciphertext: bytes = AESGCM(wrapping_key).encrypt(
            nonce, shared_key, _KEY_ENVELOPE_MAGIC
        )
        ephemeral_public_key: bytes = ephemeral_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        envelope: dict[str, str] = {
            'algorithm': _KEY_ENVELOPE_ALGORITHM,
            'curve': _KEY_ENVELOPE_CURVE,
            'ephemeral_public_key': DataSecret._b64encode(
                ephemeral_public_key
            ),
            'salt': DataSecret._b64encode(salt),
            'nonce': DataSecret._b64encode(nonce),
            'ciphertext': DataSecret._b64encode(ciphertext),
        }
        return _KEY_ENVELOPE_MAGIC + json.dumps(
            envelope, separators=(',', ':'), sort_keys=True
        ).encode('utf-8')

    def _unprotect_shared_key(self, protected_shared_key: bytes) -> bytes:
        if not isinstance(protected_shared_key, bytes):
            raise ValueError('Protected shared key must be bytes')

        if not protected_shared_key.startswith(_KEY_ENVELOPE_MAGIC):
            raise ValueError('Unsupported protected shared key format')

        if not isinstance(self.private_key, ec.EllipticCurvePrivateKey):
            raise TypeError('Data secret private key must be an EC key')

        payload: bytes = protected_shared_key[len(_KEY_ENVELOPE_MAGIC):]
        try:
            envelope = json.loads(payload.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError('Protected shared key has invalid envelope') \
                from exc

        if not isinstance(envelope, dict):
            raise ValueError('Protected shared key envelope must be an object')

        if envelope.get('algorithm') != _KEY_ENVELOPE_ALGORITHM:
            raise ValueError('Unsupported protected shared key algorithm')

        if envelope.get('curve') != _KEY_ENVELOPE_CURVE:
            raise ValueError('Unsupported protected shared key curve')

        ephemeral_public_key: bytes = DataSecret._b64decode(
            envelope, 'ephemeral_public_key'
        )
        salt: bytes = DataSecret._b64decode(envelope, 'salt')
        nonce: bytes = DataSecret._b64decode(envelope, 'nonce')
        ciphertext: bytes = DataSecret._b64decode(envelope, 'ciphertext')

        if len(salt) != _KEY_ENVELOPE_SALT_LENGTH:
            raise ValueError('Protected shared key has invalid salt length')

        if len(nonce) != _KEY_ENVELOPE_NONCE_LENGTH:
            raise ValueError('Protected shared key has invalid nonce length')

        try:
            public_key = ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256R1(), ephemeral_public_key
            )
            wrapping_key: bytes = DataSecret._derive_wrapping_key(
                self.private_key, public_key, salt
            )
            return AESGCM(wrapping_key).decrypt(
                nonce, ciphertext, _KEY_ENVELOPE_MAGIC
            )
        except (InvalidTag, ValueError) as exc:
            raise ValueError('Unable to decrypt protected shared key') \
                from exc

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

        if hash_algorithm.lower() not in CaSecret.VALID_SIGNATURE_HASHES:
            raise ValueError(f'Unsupported hash algorithm: {hash_algorithm}')
        chosen_hash = hashes.SHA256()

        digest: bytes = DataSecret._get_digest(message, chosen_hash)

        signature: bytes = self.private_key.sign(
            digest, ec.ECDSA(utils.Prehashed(chosen_hash))
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
            ec.ECDSA(utils.Prehashed(chosen_hash))
        )

    @staticmethod
    def _get_digest(message: bytes, chosen_hash: hashes) -> bytes:
        '''
        Generates a digest hash for any length of message
        '''

        hasher = hashes.Hash(chosen_hash)
        message = copy(message)
        while message:
            if len(message) > _SIGN_MAX_MESSAGE_LENGTH:
                hasher.update(message[:_SIGN_MAX_MESSAGE_LENGTH])
                message = message[_SIGN_MAX_MESSAGE_LENGTH:]
            else:
                hasher.update(message)
                message = None
        digest: bytes = hasher.finalize()

        _LOGGER.debug(f'Generated digest: {digest.hex()}')

        return digest

    @override
    async def download(self, url: str, ca_filepath: str = None,
                       network_name: str | None = None,
                       fingerprint: str | None = None) -> str | None:
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
            url, root_ca_filepath=ca_filepath, network_name=network_name,
            fingerprint=fingerprint
        )

        return cert_data
