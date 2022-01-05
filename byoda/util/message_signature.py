'''
Python module for managing signatures of documents

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
import base64
from enum import Enum
from datetime import datetime
from typing import Dict

from byoda.secrets import DataSecret
from byoda.secrets import ServiceDataSecret
from byoda.secrets import NetworkDataSecret

_LOGGER = logging.getLogger(__name__)


class SignatureType(Enum):
    NETWORK = "network"
    SERVICE = "service"


class MessageSignature:
    def __init__(self, data_secret: DataSecret,
                 hash_algorithm: str = 'SHA256'):
        '''
        Constructor

        :raises ValueError: if the class of the secret does not match the
                            type of signature
        '''

        if hash_algorithm != 'SHA256':
            raise NotImplementedError(
                f'Hash algorithm {hash_algorithm} is not supported'
            )

        self.message: str = None
        self.signature: bytes = None
        self.base64_signature: str = None
        self.timestamp: datetime = None

        self.hash_algorithm: str = hash_algorithm
        self.secret: DataSecret = data_secret
        if data_secret:
            self.certificate_cn: str = data_secret.common_name

        self.verified: bool = False

    def as_dict(self) -> Dict:
        if self.secret:
            common_name = self.secret.common_name
        else:
            common_name = 'unknown'

        data = {
            'signature': self.base64_signature,
            'hash_algorithm': self.hash_algorithm,
            'timestamp': self.timestamp.isoformat(timespec='seconds'),
            'certificate': common_name
        }
        return data

    @staticmethod
    def from_dict(data: Dict[str, str], data_secret=None):
        '''
        Factory, parse the data from the JSON Schema
        '''

        if not data:
            raise ValueError('No data in provided in dict')

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

        if not self.secret:
            raise ValueError('secret is not defined')

        self.message = message

        self.signature = self.secret.sign_message(
            message, hash_algorithm=self.hash_algorithm
        )

        self.timestamp = datetime.now()
        self.base64_signature = base64.b64encode(
            self.signature
        ).decode('utf-8')
        self.verified = True
        return self.signature

    def verify_message(self, message: str, secret: DataSecret,
                       hash_algo: str = 'SHA256'):
        '''
        Verify the digest for the message
        '''

        if not self.secret:
            raise ValueError('secret is not defined')

        self.data_secret: DataSecret = secret
        self.certificate_cn: str = secret.common_name

        if not self.certificate_cn == self.data_secret.common_name:
            raise ValueError(
                'The signing cert {} does not match the cert {}'
                'used for verfication'.format(
                    self.certificate_cn, self.secret.common_name
                )
            )

        self.data_secret.verify_message_signature(
            message, self.signature, hash_algorithm=hash_algo
        )

        self.verified = True


class ServiceSignature(MessageSignature):
    def __init__(self, secret: ServiceDataSecret, hash_algo: str = 'SHA256'):
        '''
        Constructor

        :raises ValueError: if the class of the secret does not match
        '''

        if not isinstance(secret, ServiceDataSecret):
            raise ValueError(f'Incorrect secret type {type(secret)}')

        super().__init__(secret, hash_algo)


class NetworkSignature(MessageSignature):
    def __init__(self, secret: NetworkDataSecret, hash_algo: str = 'SHA256'):
        '''
        Constructor

        :raises ValueError: if the class of the secret does not match
        '''

        if not isinstance(secret, NetworkDataSecret):
            raise ValueError(f'Incorrect secret type {type(secret)}')

        super().__init__(secret, hash_algo)
