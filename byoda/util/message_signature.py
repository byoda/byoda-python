'''
Python module for managing signatures of documents

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import base64

from enum import Enum
from typing import Self
from logging import Logger
from logging import getLogger
from datetime import datetime

from byoda.secrets.data_secret import DataSecret
from byoda.secrets.service_data_secret import ServiceDataSecret
from byoda.secrets.network_data_secret import NetworkDataSecret

_LOGGER: Logger = getLogger(__name__)


class SignatureType(Enum):
    NETWORK = "network"
    SERVICE = "service"


class MessageSignature:
    __slots__: list[str] = [
        'message', 'signature', 'base64_signature', 'timestamp',
        'hash_algorithm', 'data_secret', 'certificate_cn', 'verified'
    ]

    def __init__(self, data_secret: DataSecret,
                 hash_algorithm: str = 'SHA256') -> None:
        '''
        Constructor

        :raises: ValueError if the class of the secret does not match the
        type of signature
        '''

        if hash_algorithm != 'SHA256':
            raise NotImplementedError(
                f'Hash algorithm {hash_algorithm} is not supported'
            )

        self.message: str | None = None
        self.signature: bytes | None = None
        self.base64_signature: str | None = None
        self.timestamp: datetime | None = None

        self.hash_algorithm: str = hash_algorithm
        self.data_secret: DataSecret = data_secret
        if self.data_secret:
            self.certificate_cn: str = self.data_secret.common_name

        self.verified: bool = False

    def as_dict(self) -> dict:
        if self.data_secret:
            common_name: str | None = self.data_secret.common_name
        else:
            common_name = 'unknown'

        data: dict[str, any] = {
            'signature': self.base64_signature,
            'hash_algorithm': self.hash_algorithm,
            'timestamp': self.timestamp.isoformat(timespec='seconds'),
            'certificate': common_name
        }
        return data

    @staticmethod
    def from_dict(data: dict[str, str], data_secret=None) -> Self:
        '''
        Factory, parse the data from the JSON Schema
        '''

        if not data:
            raise ValueError('No signatures available in service schema')

        sig = MessageSignature(data_secret, data['hash_algorithm'])
        sig.base64_signature = data['signature']
        sig.signature = base64.b64decode(sig.base64_signature)
        sig.timestamp = datetime.fromisoformat(data['timestamp'])
        sig.certificate_cn = data['certificate']

        return sig

    def sign_message(self, message: str) -> bytes:
        '''
        Sign a message with an assymetric secret
        '''

        if not self.data_secret:
            raise ValueError('secret is not defined')

        self.message = message

        self.signature = self.data_secret.sign_message(
            message, hash_algorithm=self.hash_algorithm
        )

        self.timestamp = datetime.now()
        self.base64_signature = base64.b64encode(
            self.signature
        ).decode('utf-8')
        self.verified = True
        return self.signature

    def verify_message(self, message: str, data_secret: DataSecret = None,
                       signature: bytes = None, hash_algo: str = 'SHA256'
                       ) -> None:
        '''
        Verify the digest for the message
        '''

        if data_secret:
            self.data_secret: DataSecret = data_secret
            self.certificate_cn: str = data_secret.common_name

        if not self.data_secret:
            raise ValueError('secret is not defined')

        if self.certificate_cn != self.data_secret.common_name:
            raise ValueError(
                'The signing cert {} does not match the cert {}'
                'used for verfication'.format(
                    self.certificate_cn, self.data_secret.common_name
                )
            )

        if signature:
            self.signature = signature

        if not self.signature:
            raise ValueError('no signature available to verify')

        self.data_secret.verify_message_signature(
            message, self.signature, hash_algorithm=hash_algo
        )

        self.verified = True


class ServiceSignature(MessageSignature):
    def __init__(self, secret: ServiceDataSecret, hash_algo: str = 'SHA256') -> None:
        '''
        Constructor

        :raises ValueError: if the class of the secret does not match
        '''

        if not isinstance(secret, ServiceDataSecret):
            raise ValueError(f'Incorrect secret type {type(secret)}')

        super().__init__(secret, hash_algo)


class NetworkSignature(MessageSignature):
    def __init__(self, secret: NetworkDataSecret, hash_algo: str = 'SHA256') -> None:
        '''
        Constructor

        :raises ValueError: if the class of the secret does not match
        '''

        if not isinstance(secret, NetworkDataSecret):
            raise ValueError(f'Incorrect secret type {type(secret)}')

        super().__init__(secret, hash_algo)
