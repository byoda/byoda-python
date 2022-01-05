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
    def __init__(self):
        '''
        Constructur for the KVCache base class
        '''

        server = config.server

        self.namespace = f'{server.network.name}:{type(server)}:'

    @staticmethod
    def create(connection_string: str,
               cache_tech: CacheTech = CacheTech.REDIS):
        '''
        Factory for a KV Cache
        '''

        if not connection_string:
            raise ValueError('No connection string provided')

        if cache_tech == CacheTech.REDIS:
            from .kv_redis import KvRedis
            kvr = KvRedis(connection_string)
            return kvr
        else:
            raise ValueError(f'Unsupported cache tech: {cache_tech.value}')

    @abstractmethod
    def get(self, key: str):
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value, cache: int = DEFAULT_CACHE_EXPIRATION):
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

    @abstractmethod
    def delete(self, key: str) -> bool:
        raise NotImplementedError

    def get_annotated_key(self, key: str) -> str:
        '''
        Annotate the key so that it is unique to the server. The resulting
        key will always be a string.
        '''

        return self.namespace + str(key)
