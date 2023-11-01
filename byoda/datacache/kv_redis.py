'''
The KV Redis data cache provides ephemeral data storage, such as services
storing data about their members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from logging import getLogger

import orjson

import redis.asyncio as redis

from .kv_cache import KVCache, DEFAULT_CACHE_EXPIRATION

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)


class KVRedis(KVCache):
    def __init__(self, identifier: str = None):
        '''
        Constructor. Do not call directly, use the factory KVRedis.setup()
        instead

        :param connection_string: format 'host:port:password'
        :param identifier: string to include when formatting the key,
        typically this would be the service_id
        '''

        self.default_cache_expiration = DEFAULT_CACHE_EXPIRATION

        super().__init__(identifier=identifier)

        self.driver = None

    async def setup(connection_string: str, identifier: str = None):
        '''
        Factory for KVRedis class
        '''

        self: KVRedis = KVRedis(identifier)

        self.driver = await redis.from_url(connection_string)

        return self

    async def exists(self, key: str) -> bool:
        '''
        Checks if the key exists in the cache
        '''

        key = self.get_annotated_key(key)

        ret = await self.driver.exists(key)

        exists = ret != 0

        _LOGGER.debug(f'Key {key} exist: {exists}')

        return exists

    async def get(self, key: str) -> object:
        '''
        Gets the value for the specified key from the cache. If the value
        retrieved on the cache is a string that starts with '{' and ends with
        '}' then an attempt is made to parse the string as JSON. If the parsing
        succeeds, the resulting object is returned.
        '''

        key = self.get_annotated_key(key)

        value = await self.driver.get(key)

        _LOGGER.debug(f'Got value {value} for key {key}')
        if isinstance(value, bytes):
            data = value.decode('utf-8')
            _LOGGER.debug(f'Converted data to string: {data}')

            if len(data) > 1 and data[0] == '{' and data[-1] == '}':
                try:
                    _LOGGER.debug('Attempting to deserialize JSON data')
                    data = orjson.loads(value)
                    value = data
                except orjson.JSONDecodeError:
                    pass

        return value

    async def pos(self, key: str, value: str) -> int:
        '''
        Finds the first occurrence of value in the list for the key
        '''

        key = self.get_annotated_key(key)

        pos = await self.driver.lpos(key, value)

        if pos is not None:
            _LOGGER.debug(
                f'Found {value} in position {pos} of list for key {key}'
            )
        else:
            _LOGGER.debug(
                f'Did not find value {value} in the list for key {key}'
            )

        return pos

    async def get_next(self, key, timeout: int = 0) -> object:
        '''
        Gets the first item of a list value for the key
        '''

        key = self.get_annotated_key(key)

        value = await self.driver.blpop(key, timeout=timeout)

        if type(value) in (list, tuple):
            value = value[-1]

        _LOGGER.debug(f'Popped {value} from start of list for key {key}')

        return value

    async def set(self, key: str, value: object,
                  expiration: int = DEFAULT_CACHE_EXPIRATION) -> bool:
        '''
        Sets a key to the specified value. If the value is a dict
        or a list then it gets converted to a JSON string
        '''

        key = self.get_annotated_key(key)

        if type(value) in (list, dict):
            value = orjson.dumps(value)

        ret = await self.driver.set(key, value, ex=expiration)

        _LOGGER.debug(f'Set key {key} to value {value}')

        return ret

    async def delete(self, key: str) -> bool:
        '''
        Deletes the key
        '''

        key = self.get_annotated_key(key)

        ret = await self.driver.delete(key)

        _LOGGER.debug(f'Deleted key {key}')

        return ret

    async def shift_push_list(self, key: str, wait: bool = True,
                              timeout: int = 0) -> object:
        '''
        atomically shifts a value from the start of a list 'key' and appends
        it to the end of the list.
        '''

        key = self.get_annotated_key(key)

        if not wait:
            value = await self.driver.lmove(key, key, src='LEFT', dest='RIGHT')
        else:
            value = await self.driver.blmove(
                key, key, src='LEFT', dest='RIGHT', timeout=timeout
            )

        _LOGGER.debug(
            f'Got moved value {value} from begin to end of key {key}'
        )

        return value

    async def get_list(self, key) -> object:
        '''
        Gets the list value of a key
        '''

        key = self.get_annotated_key(key)

        ret = await self.driver.lrange(key, 0, -1)

        _LOGGER.debug(f'Got list for key {key} with length {len(ret)}')

        return ret

    async def remove_from_list(self, key: str, value: str) -> object:
        '''
        Removes the first occurrence of a value from a list.

        :returns: number of occurrences removed
        '''

        key = self.get_annotated_key(key)

        result = await self.driver.lrem(key, 1, value)

        _LOGGER.debug(f'Removed {result} items from list for key {key}')

        return result

    async def shift(self, key: str) -> object:
        '''
        Removes the first item from the list and
        returns it
        '''

        key = self.get_annotated_key(key)

        val = await self.driver.blpop(key, timeout=0)

        _LOGGER.debug(f'Shifted value {val} from key {key}')

        return val

    async def push(self, key: str, value: object) -> int:
        '''
        Pushes a value to the list specified by 'key'
        '''

        key = self.get_annotated_key(key)

        ret = await self.driver.rpush(key, value)

        _LOGGER.debug(f'Pushed value {value} to end of list for key {key}')

        return ret

    async def pop(self, key: str) -> object:
        '''
        Pops a value from the list specified by 'key'
        '''

        key = self.get_annotated_key(key)

        val = await self.driver.rpop(key)

        _LOGGER.debug(f'Popped value {val} from end of list for key {key}')

        return val

    async def incr(self, key: str, amount: int = 1,
                   expiration=DEFAULT_CACHE_EXPIRATION) -> int:
        '''
        Increments a counter, creates the counter is it doesn't exist already
        '''

        key = self.get_annotated_key(key)

        if not await self.exists(key):
            await self.set(key, 0, expiration=expiration)

        value = await self.driver.incr(key, amount)

        return int(value)

    async def decr(self, key: str, amount: int = 1,
                   expiration=DEFAULT_CACHE_EXPIRATION) -> int:
        '''
        Decrements a counter, sets it to 0 if it does not exist
        or goes below 0
        '''

        key = self.get_annotated_key(key)

        if not await self.exists(key):
            await self.set(key, 0, expiration=expiration)

        value = await self.driver.decr(key, amount)
        if int(value) < 0:
            await self.driver.set(key, 0)
            value = 0

        return int(value)
