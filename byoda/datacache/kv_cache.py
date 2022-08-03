'''
The kv cache handles storing the data of a service

It works on the basis of a cache-key. There is no hierarchical relationships
for cache keys, such as there is for the document store. The KV-cache does not
provide encryption/decryption capabilities

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from abc import ABC, abstractmethod

from byoda import config

from byoda.datatypes import CacheTech

_LOGGER = logging.getLogger(__name__)

# 3 days default expiration
DEFAULT_CACHE_EXPIRATION = 3 * 24 * 60 * 60


class KVCache(ABC):
    def __init__(self, identifier: str = None):
        '''
        Constructur for the KVCache base class

        :param identifier: string to include in the key annotation
        '''

        # We can't set namespace here as the config.server object may not
        # have been set yet at this stage of the initialization of the server
        self.namespace = None

        if identifier is not None:
            self.identifier = identifier
        else:
            self.identifier = ''

    @staticmethod
    def create(connection_string: str, identifier: str = None,
               cache_tech: CacheTech = CacheTech.REDIS):
        '''
        Factory for a KV Cache

        :param connection_string: connection string for Redis server
        :param identifier: string to include in the key annotation
        :param chache_tech: the cache technology to use, only Redis is
        supported at this time
        '''

        if not connection_string:
            raise ValueError('No connection string provided')

        if cache_tech == CacheTech.REDIS:
            from .kv_redis import KVRedis
            kvr = KVRedis(connection_string, identifier)
            return kvr
        else:
            raise ValueError(f'Unsupported cache tech: {cache_tech.value}')

    def get_annotated_key(self, key: str) -> str:
        '''
        Annotate the key so that it is unique to the server. The resulting
        key will always be a string.
        '''

        if not self.namespace:
            self.namespace = config.server.network.name + self._identifier

        return f'{config.server.server_type.value}:{self.namespace}:{str(key)}'

    @abstractmethod
    def get(self, key: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def pos(self, key: str, value: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def get_next(self, key: str, timeout: int = 0) -> object:
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value, cache: int = DEFAULT_CACHE_EXPIRATION
            ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def push(self, key: str, value: object) -> int:
        raise NotImplementedError

    @abstractmethod
    def pop(self, key: str) -> object:
        raise NotImplementedError

    @abstractmethod
    def shift_push_list(self, key: str, wait: bool = True):
        raise NotImplementedError

    def get_list(self, key):
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> bool:
        raise NotImplementedError

    @property
    def identifier(self):
        return self._identifier

    @identifier.setter
    def identifier(self, value: str):
        if self.namespace:
            raise ValueError(
                'Can not set identifier after first access to the cache'
            )

        self._identifier = '-' + str(value)
