'''
Bring your own algorithm backend storage for the server.

The directory server uses caching storage for server and client registrations
The profile server uses noSQL storage for profile data

:maintainer : Steven Hessing (stevenhessing@live.com)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

from abc import ABC, abstractmethod
import logging
from enum import Enum

_LOGGER = logging.getLogger(__name__)


class CacheStorageType(Enum):
    REDIS = 'redis'     # noqa


class CacheStorage(ABC):
    def __init__(self):
        self.server = None
        self.host = None
        self.port = None
        self.password = None

    @staticmethod
    def connect(config):
        product = CacheStorageType(config['product'])
        if product == CacheStorageType.REDIS:
            from .redis import RedisCacheStorage
            return RedisCacheStorage.connect(config)
        else:
            raise ValueError('Unknown cache storage product: {product}')

    @abstractmethod
    def get(self, key):
        raise NotImplementedError

    @abstractmethod
    def set(self, key, value):
        raise NotImplementedError

    @abstractmethod
    def incr(self, key):
        raise NotImplementedError

    @abstractmethod
    def incrby(self, key, value):
        raise NotImplementedError

    @abstractmethod
    def decr(self, key):
        raise NotImplementedError

    @abstractmethod
    def decrby(self, key, value):
        raise NotImplementedError

    @abstractmethod
    def exists(self, key):
        raise NotImplementedError

    @abstractmethod
    def delete(self, key):
        raise NotImplementedError
