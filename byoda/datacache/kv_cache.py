'''
The kv cache handles storing the data of a service

It works on the basis of a cache-key. There is no hierarchical relationships
for cache keys, such as there is for the document store. The KV-cache does not
provide encryption/decryption capabilities

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from typing import Self
from logging import getLogger
from typing import TypeVar
from abc import ABC, abstractmethod


from byoda.datatypes import CacheTech
from byoda.datatypes import CacheType

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)

Server = TypeVar('Server')

# TODO: review
# ldbm at https://pypi.org/project/lmdbm/
# leveldb at https://github.com/wbolster/plyvel


class KVCache(ABC):
    DEFAULT_CACHE_EXPIRATION = 3 * 24 * 60 * 60

    def __init__(self, service_id: int | None = None,
                 network_name: str | None = None,
                 server_type: str | None = None,
                 identifier: str | None = None) -> None:
        '''
        Constructur for the KVCache base class. The parameters are used to
        to generate a namespace (prefix) for the keys in the cache. The
        namespace always ends with ':'

        :param identifier: string to include in the key annotation
        :param network_name: network_name to include in the key annotation
        :param server_type: server_type to include in the key annotation
        :returns: self
        '''

        self.namespace: str = f'{server_type}:{network_name}-{service_id}:'

        if identifier:
            self.namespace += f'{identifier.rstrip(":")}:'

        self.service_id: int = service_id

    @staticmethod
    async def create(connection_string: str, network_name: str | None = None,
                     service_id: int | None = None,
                     server_type: Server | None = None,
                     cache_tech: CacheTech = CacheTech.REDIS,
                     cache_type: CacheType = None) -> Self:
        '''
        Factory for a KV Cache

        :param connection_string: connection string for Redis server
        :param identifier: string to include in the key annotation
        :param chache_tech: the cache technology to use, Redis and Sqlite are
        supported at this time
        '''

        if not connection_string:
            raise ValueError('No connection string provided')

        if cache_tech == CacheTech.SQLITE:
            from .kv_sqlite import KVSqlite
            kvs: KVSqlite = await KVSqlite.create(
                connection_string, cache_type
            )
            return kvs
        elif cache_tech == CacheTech.REDIS:
            from .kv_redis import KVRedis
            kvr: KVRedis = await KVRedis.setup(
                connection_string, service_id=service_id,
                network_name=network_name, server_type=server_type,
                cache_type=cache_type
            )
            return kvr
        elif cache_tech == CacheTech.POSTGRES:
            raise NotImplementedError(
                'Caching with postgres is not yet implemented'
            )
        else:
            raise ValueError(f'Unsupported cache tech: {cache_tech.value}')

    async def close(self) -> None:
        '''
        Close the connection to the cache
        '''

        raise NotImplementedError

    def get_annotated_key(self, key: str) -> str:
        '''
        Annotate the key so that it is unique to the server. The resulting
        key will always be a string.
        '''

        value: str = f'{self.namespace}{str(key)}'

        return value

    @abstractmethod
    def exists(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get(self, key: str) -> object | None:
        '''
        Returns None if key is not in the cache
        '''

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

    def get_list(self, key: str):
        raise NotImplementedError

    async def incr(self, key: str, value: int = 1) -> int:
        raise NotImplementedError

    async def decr(self, key: str, value: int = 1) -> int:
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
