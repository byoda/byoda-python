'''
The KV Redis data cache provides ephemeral data storage, such as services storing
data about their members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

from redis import Redis

from .kv_cache import KVCache, DEFAULT_CACHE_EXPIRATION

_LOGGER = logging.getLogger(__name__)


class KVRedis(KVCache):
    def __init__(self, connection_string: str):
        '''
        Constructor

        :param connection_string: format 'host:port:password'
        '''

        params = connection_string.split(':', 2)
        self.host = None
        self.port = None
        self.password = None
        if len(params) >= 1:
            self.host = params[0]
        if len(params) >= 2:
            self.port = params[1]
            if not self.port:
                self.port = None
        if len(params) == 3:
            self.password = params[2]
            if not self.password:
                self.password = None

        if not self.host:
            raise ValueError(
                'A Redis host must be specified in the connection_string'
            )

        super().__init__()

        self.driver = Redis(
            host=self.host, port=self.port, password=self.password
        )

    def exists(self, key: str) -> bool:
        '''
        Checks if the key exists in the cache
        '''

        key = self.get_annotated_key(key)

        ret = self.driver.exists(key)

        return ret != 0

    def get(self, key: str) -> object:
        '''
        Gets the value for the specified key from the cache
        '''

        key = self.get_annotated_key(key)

        value = self.driver.get(key)

        return value

    def set(self, key: str, value: object,
            expiration=DEFAULT_CACHE_EXPIRATION) -> int:
        '''
        Sets a key to the specified value
        '''

        key = self.get_annotated_key(key)

        ret = self.driver.set(key, value, expiration)

        return ret

    def delete(self, key: str) -> bool:
        '''
        Deletes the key
        '''

        key = self.get_annotated_key(key)

        ret = self.driver.delete(key)

        return ret

    def shift_push_list(self, key: str, wait: bool = True):
        '''
        atomically shifts a value from the start of a list 'key' and appends
        it to the end of the list.
        '''

        key = self.get_annotated_key(key)

        if not wait:
            value = self.driver.lmove(
                key, self.namespace + key, src='LEFT', dest='RIGHT'
            )
        else:
            value = self.driver.blmove(
                key, self.namespace + key, src='LEFT', dest='RIGHT'
            )

        return value

    def push(self, key: str, value: object) -> int:
        '''
        Pushes a value to the list specified by 'key'
        '''

        key = self.get_annotated_key(key)

        ret = self.driver.rpush(key, value)

        return ret

    def pop(self, key: str) -> object:
        '''
        Pops a value from the list specified by 'key'
        '''

        key = self.get_annotated_key(key)

        val = self.driver.rpop(key)

        return val
