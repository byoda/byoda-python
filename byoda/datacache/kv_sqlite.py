'''
The KV Redis data cache provides ephemeral data storage, such as services
storing data about their members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
from uuid import UUID
from datetime import datetime, timezone, timedelta

import orjson

import aiosqlite

from .kv_cache import KVCache

_LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_EXPIRATION = 60 * 60 * 24 * 7  # 7 days


def dict_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}


class KVSqlite(KVCache):
    def __init__(self, cache_file: str):
        '''
        Constructor

        :param cache_file: full path to the Sqlite DB file
        :param identifier: not used
        '''

        super().__init__(identifier=None)
        self.default_cache_expiration = DEFAULT_CACHE_EXPIRATION
        self.cache_file = cache_file

    @staticmethod
    async def create(cache_file: str):
        cache = KVSqlite(cache_file)

        _LOGGER.debug(f'Connecting to Sqlite DB: {cache_file}')
        async with aiosqlite.connect(cache_file, isolation_level=None
                                     ) as db_conn:
            _LOGGER.debug('Creating querycache table')
            await db_conn.execute('''
                CREATE TABLE IF NOT EXISTS querycache(
                    query_id TEXT PRIMARY KEY,
                    data TEXT,
                    expires INTEGER
                ) STRICT
            ''')

        return cache

    async def close(self):
        '''
        Closes the database connection
        '''

        pass

    async def exists(self, key: str) -> bool | None:
        '''
        Checks if a key exists in the cache
        '''

        try:
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                db_conn.row_factory = dict_factory

                _LOGGER.debug(f'Checking if key {key} exists in the cache')
                rows = await db_conn.execute_fetchall(
                    'SELECT * FROM querycache WHERE query_id = :query_id',
                    {'query_id': str(key)}
                )
            _LOGGER.debug(f'Found {rows} rows for cache key {key}')
            return len(rows) > 0
        except aiosqlite.OperationalError as exc:
            _LOGGER.debug(f'Checking for key {key} failed: {exc}')
            return None

    async def get(self, key: str) -> object:
        '''
        Gets the values for a key from the cache
        '''

        try:
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                db_conn.row_factory = dict_factory

                _LOGGER.debug(f'Getting key {key} from cache')
                rows = await db_conn.execute_fetchall(
                    'SELECT * FROM querycache WHERE query_id = :query_id',
                    {'query_id': str(key)}
                )

        except aiosqlite.OperationalError as exc:
            _LOGGER.debug(f'Getting key {key} failed: {exc}')
            return None

        _LOGGER.debug(f'Found {len(rows)} rows for cache key {key}')

        if len(rows) > 1:
            raise ValueError(f'More than 1 row returned for key: {key}')

        if len(rows) == 0:
            return None

        data = rows[0]['data']
        return orjson.loads(data)

    async def set(self, key: str, value: object,
                  expiration: int = DEFAULT_CACHE_EXPIRATION) -> bool:
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
                now = datetime.now(tz=timezone.utc)
                expires = now + timedelta(seconds=expiration)
                data = orjson.dumps(value).decode('utf-8')
                _LOGGER.debug(
                    f'Inserting key {key} with value {data} into cache'
                )
                result = await db_conn.execute(
                    'INSERT INTO querycache VALUES (:key, :data, :expiration)',        # noqa: E501
                    {
                        'key': key,
                        'data': data,
                        'expiration': int(expires.timestamp())
                    }
                )
                return result.rowcount == 1
        except aiosqlite.IntegrityError as exc:
            _LOGGER.debug(f'Inserting key {key} failed primary key: {exc}')
            return False

    async def delete(self, key: str | UUID) -> bool:
        try:
            _LOGGER.debug(f'Deleting key {key} from the cache')
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                db_conn.row_factory = dict_factory
                result = await db_conn.execute(
                    'DELETE FROM querycache WHERE query_id = :key',
                    {'key': key}
                )
                _LOGGER.debug(
                    f'Deleted {result.rowcount} row(s) for key {key}'
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
        try:
            _LOGGER.debug(f'Purging expired keys from the cache {str(now)}')
            async with aiosqlite.connect(self.cache_file, isolation_level=None
                                         ) as db_conn:
                result = await db_conn.execute(
                    'DELETE FROM querycache WHERE expires < :timestamp',
                    {'timestamp': int(now.timestamp())}
                )
                return result.rowcount
        except Exception as exc:
            _LOGGER.warning(f'Purging query cache failed: {exc}')
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
