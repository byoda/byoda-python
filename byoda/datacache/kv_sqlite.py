'''
The KV Redis data cache provides ephemeral data storage, such as services
storing data about their members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger
from datetime import datetime
from datetime import timezone
from datetime import timedelta

import orjson

import aiosqlite

from byoda.datatypes import CacheType

from byoda.datacache.kv_cache import KVCache

_LOGGER: Logger = getLogger(__name__)

DEFAULT_CACHE_EXPIRATION = 60 * 60 * 24 * 7  # 7 days


def dict_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}


class KVSqlite(KVCache):
    def __init__(self, cache_file: str, cache_type: CacheType):
        '''
        Constructor

        :param cache_file: full path to the Sqlite DB file
        :param identifier: not used
        '''

        super().__init__(identifier=None)
        self.default_cache_expiration = KVCache.DEFAULT_CACHE_EXPIRATION
        self.cache_file = cache_file
        self.cache_type: CacheType = cache_type

    async def close(self):
        '''
        Closes the database connection
        '''

        pass

    def _get_table_name(self):
        '''
        Gets the name of the SQL table for the cache
        '''

        return f'BYODA_{self.cache_type.value}'

    @staticmethod
    async def create(connection_string: str, cache_type: CacheType):
        cache = KVSqlite(connection_string, cache_type)

        _LOGGER.debug(f'Connecting to Cache: {connection_string}')
        async with aiosqlite.connect(connection_string, isolation_level=None
                                     ) as db_conn:
            if not cache_type:
                raise ValueError(f'Invalida cache type: {cache_type.value}')

            table_name: str = cache._get_table_name()
            _LOGGER.debug(f'Creating {table_name} cache table')
            await db_conn.execute(
                f'CREATE TABLE IF NOT EXISTS {table_name}('
                f'    key TEXT PRIMARY KEY,'
                f'    data TEXT,'
                f'    expires INTEGER'
                f') STRICT'
            )

        return cache

    async def exists(self, key: str) -> bool | None:
        '''
        Checks if a key exists in the cache
        '''

        try:
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                db_conn.row_factory = dict_factory

                cache_type: str = self.cache_type.value
                table_name: str = self._get_table_name()

                _LOGGER.debug(
                    f'Checking if key {key} exists in cache {cache_type}'
                )
                rows = await db_conn.execute_fetchall(
                    f'SELECT * FROM {table_name} WHERE key = :value',
                    {'value': str(key)}
                )
            _LOGGER.debug(
                f'Found {rows} rows for cache key {key} for cache {cache_type}'
            )
            return len(rows) > 0
        except aiosqlite.OperationalError as exc:
            _LOGGER.debug(
                f'Checking for key {key} in cache {cache_type} failed: {exc}'
            )
            return None

    async def get(self, key: str) -> object | None:
        '''
        Gets the values for a key from the cache

        :returns: None if key does not exist
        '''

        try:
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                db_conn.row_factory = dict_factory

                cache_type: str = self.cache_type.value
                table_name: str = self._get_table_name()

                _LOGGER.debug(f'Getting key {key} from cache {cache_type}')
                rows = await db_conn.execute_fetchall(
                    f'SELECT * FROM {table_name} WHERE key = :value',
                    {'value': str(key)}
                )

        except aiosqlite.OperationalError as exc:
            _LOGGER.debug(
                f'Getting key {key} from cache {cache_type} failed: {exc}'
            )
            return None

        _LOGGER.debug(
            f'Found {len(rows)} rows for key {key} in cache {cache_type}'
        )

        if len(rows) > 1:
            raise ValueError(
                f'More than 1 row returned for key {key} in cache {cache_type}'
            )

        if len(rows) == 0:
            return None

        data = rows[0]['data']
        return orjson.loads(data)

    async def set(self, key: str, value: object,
                  expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION) -> bool:
        '''
        Sets the key with values in the cache. The value with be serialized
        for storage in

        :param key: the key to set
        :param value: the value to set
        :param expiration: the expiration time in seconds
        :returns: True if the key was set, False otherwise
        '''

        try:
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                cache_type: str = self.cache_type.value
                table_name: str = self._get_table_name()

                now = datetime.now(tz=timezone.utc)
                expires = now + timedelta(seconds=expiration)
                data = orjson.dumps(value).decode('utf-8')
                _LOGGER.debug(
                    f'Inserting key {key} with value {data} into cache '
                    f'{cache_type}'
                )
                result = await db_conn.execute(
                    f'INSERT INTO {table_name} '
                    f'VALUES (:key, :data, :expiration)',
                    {
                        'key': key,
                        'data': data,
                        'expiration': int(expires.timestamp())
                    }
                )
                return result.rowcount == 1
        except aiosqlite.IntegrityError as exc:
            _LOGGER.debug(
                f'Inserting key {key} in cache {cache_type} failed '
                f'for primary key: {exc}'
            )
            return False

    async def incr(self, key: str | UUID, value: int = 1,
                   expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION) -> int:
        '''
        increments the value for the key in the cache

        :returns: None if key not in the cache
        :raises: ValueError if the value for the key is not an int
        '''

        cache_type: str = self.cache_type.value
        _LOGGER.debug(
            f'Incrementing key {key} with value {value} into cache '
            f'{cache_type}'
        )

        # TODO: put get and set in a single SQL transaction
        current_value = await self.get(key)
        if current_value is None:
            return None

        try:
            new_value = max(0, int(current_value) + value)
        except ValueError as exc:
            _LOGGER.exception(
                f'Can not increment non-integer value {type(current_value)}: '
                f'{exc}'
            )
            raise

        try:
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                table_name: str = self._get_table_name()

                now = datetime.now(tz=timezone.utc)
                expires = now + timedelta(seconds=expiration)
                data = orjson.dumps(new_value).decode('utf-8')
                _LOGGER.debug(
                    f'Updating key {key} with value {data} into cache '
                    f'{cache_type}'
                )
                await db_conn.execute(
                    f'UPDATE {table_name} '
                    f'SET data = :data, expires = :expiration '
                    f'WHERE key = :key',
                    {
                        'key': key,
                        'data': data,
                        'expiration': int(expires.timestamp())
                    }
                )
        except aiosqlite.IntegrityError as exc:
            _LOGGER.exception(
                f'Update key {key} in cache {cache_type} failed: {exc}'
            )
            return RuntimeError

        return new_value

    async def decr(self, key: str | UUID, value: int = 1,
                   expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION) -> int:
        '''
        increments the value for the key in the cache

        :returns: None if key not in the cache
        :raises: ValueError if the value for the key is not an int
        '''

        cache_type: str = self.cache_type.value
        _LOGGER.debug(
            f'Decrementing key {key} with value {value} into cache '
            f'{cache_type}'
        )

        # TODO: put get and set in a single SQL transaction
        current_value = await self.get(key)
        if current_value is None:
            return None

        try:
            new_value = max(0, int(current_value) - value)
        except ValueError as exc:
            _LOGGER.exception(
                f'Can not decrement non-integer value {type(current_value)}: '
                f'{exc}'
            )
            raise

        try:
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                table_name: str = self._get_table_name()

                now = datetime.now(tz=timezone.utc)
                expires = now + timedelta(seconds=expiration)
                data = orjson.dumps(new_value).decode('utf-8')
                _LOGGER.debug(
                    f'Updating key {key} with value {data} into cache '
                    f'{cache_type}'
                )
                await db_conn.execute(
                    f'UPDATE {table_name} '
                    f'SET data = :data, expires = :expiration'
                    f'WHERE key = :key',
                    {
                        'key': key,
                        'data': data,
                        'expiration': int(expires.timestamp())
                    }
                )
        except aiosqlite.IntegrityError as exc:
            _LOGGER.exception(
                f'Update key {key} in cache {cache_type} failed: {exc}'
            )
            return RuntimeError

        return new_value

    async def delete(self, key: str | UUID) -> bool:
        try:
            _LOGGER.debug(f'Deleting key {key} from the cache')
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                db_conn.row_factory = dict_factory

                cache_type: str = self.cache_type.value
                table_name: str = self._get_table_name()

                result = await db_conn.execute(
                    f'DELETE FROM {table_name} WHERE key = :key',
                    {'key': key}
                )
                _LOGGER.debug(
                    f'Deleted {result.rowcount} row(s) for key {key}'
                    f'from cache {cache_type}'
                )
                return result.rowcount > 0
        except Exception as exc:
            _LOGGER.debug(f'Deleting key {key} failed: {exc}')
            return False

    async def purge(self) -> int:
        '''
        Purges all expired keys from the cache
        '''

        now = datetime.now(tz=timezone.utc)
        cache_type: str = self.cache_type.value
        try:
            _LOGGER.debug(f'Purging expired keys from the cache {str(now)}')
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                table_name: str = self._get_table_name()

                result = await db_conn.execute(
                    f'DELETE FROM {table_name} '
                    f'WHERE expires < :timestamp',
                    {'timestamp': int(now.timestamp())}
                )
                return result.rowcount
        except Exception as exc:
            _LOGGER.warning(f'Purging cache {cache_type} failed: {exc}')
            return False

    def get_next(self):
        return NotImplementedError

    def pop(self):
        return NotImplementedError

    def pos(self):
        return NotImplementedError

    def push(self):
        return NotImplementedError

    def shift_push_list(self):
        return NotImplementedError
