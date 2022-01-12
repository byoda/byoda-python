'''
The KV Redis data cache provides ephemeral data storage, such as services
storing data about their members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

from json.decoder import JSONDecodeError
import logging
import json

from redis import Redis

from .kv_cache import KVCache, DEFAULT_CACHE_EXPIRATION

_LOGGER = logging.getLogger(__name__)


class KVRedis(KVCache):
    def __init__(self, connection_string: str, identifier: str = None):
        '''
        Constructor

        :param connection_string: format 'host:port:password'
        :param identifier: string to include when formatting the key,
        typically this would be the service_id
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

        super().__init__(identifier=identifier)

        self.driver = Redis(
            host=self.host, port=self.port, password=self.password
        )

    def exists(self, key: str) -> bool:
        '''
        Checks if the key exists in the cache
        '''

        key = self.get_annotated_key(key)

        ret = self.driver.exists(key)

        exists = ret != 0

        _LOGGER.debug(f'Does key {key} exist: {exists}')

        return exists

    def get(self, key: str) -> object:
        '''
        Gets the value for the specified key from the cache. If the value
        retrieved on the cache is a string that starts with '{' and ends with
        '}' then an attempt is made to parse the string as JSON. If the parsing
        succeeds, the resulting object is returned.
        '''

        key = self.get_annotated_key(key)

        value = self.driver.get(key)

        _LOGGER.debug(f'Got value {value} for key {key}')
        if isinstance(value, bytes):
            data = value.decode('utf-8')
            if len(data) > 1 and data[0] == '{' and data[-1] == '}':
                try:
                    data = json.loads(value)
                    value = data
                except JSONDecodeError:
                    pass

        return value

    def pos(self, key: str, value: str) -> int:
        '''
        Finds the first occurrence of value in the list for the key
        '''

        key = self.get_annotated_key(key)

        pos = self.driver.lpos(key, value)

        if pos is not None:
            _LOGGER.debug(
                f'Found {value} in position {pos} of list for key {key}'
            )
        else:
            _LOGGER.debug(
                f'Did not find value {value} in the list for key {key}'
            )

        return pos

    def get_next(self, key, timeout: int = 0) -> object:
        '''
        Gets the first item of a list value for the key
        '''

        key = self.get_annotated_key(key)

        value = self.driver.blpop(key, timeout=timeout)

        if isinstance(value, tuple):
            value = value[-1]

        _LOGGER.debug(f'Popped {value} from start of list for key {key}')

        return value

    def set(self, key: str, value: object,
            expiration=DEFAULT_CACHE_EXPIRATION) -> bool:
        '''
        Sets a key to the specified value. If the value is a dict
        then it gets converted to a JSON string
        '''

        key = self.get_annotated_key(key)

        if isinstance(value, dict):
            value = json.dumps(value)

        ret = self.driver.set(key, value, ex=expiration)

        _LOGGER.debug(f'Set key {key} to value {value}')

        return ret

    def delete(self, key: str) -> bool:
        '''
        Deletes the key
        '''

        key = self.get_annotated_key(key)

        ret = self.driver.delete(key)

        _LOGGER.debug(f'Deleted key {key}')

        return ret

    def shift_push_list(self, key: str, wait: bool = True, timeout: int = 0):
        '''
        atomically shifts a value from the start of a list 'key' and appends
        it to the end of the list.
        '''

        key = self.get_annotated_key(key)

        if not wait:
            value = self.driver.lmove(key, key, src='LEFT', dest='RIGHT')
        else:
            value = self.driver.blmove(
                key, key, src='LEFT', dest='RIGHT', timeout=timeout
            )

        _LOGGER.debug(
            f'Got moved value {value} from begin to end of key {key}'
        )

        return value

    def get_list(self, key):
        '''
        Gets the list value of a key
        '''

        key = self.get_annotated_key(key)

        ret = self.driver.lrange(key, 0, -1)

        _LOGGER.debug(f'Got list for key {key} with length {len(ret)}')

        return ret

    def shift(self, key: str) -> object:
        '''
        Removes the first item from the list and
        returns it
        '''

        key = self.get_annotated_key(key)

        val = self.driver.blpop(key, timeout=0)

        _LOGGER.debug(f'Shifted value {val} from key {key}')

        return val

    def push(self, key: str, value: object) -> int:
        '''
        Pushes a value to the list specified by 'key'
        '''

        key = self.get_annotated_key(key)

        ret = self.driver.rpush(key, value)

        _LOGGER.debug(f'Pushed value {value} to end of list for key {key}')

        return ret

    def pop(self, key: str) -> object:
        '''
        Pops a value from the list specified by 'key'
        '''

        key = self.get_annotated_key(key)

        val = self.driver.rpop(key)

        _LOGGER.debug(f'Popped value {val} from end of list for key {key}')

        return val
