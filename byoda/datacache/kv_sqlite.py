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

    @staticmethod
    async def create(cache_file, identifier: str = None):
        cache = KVSqlite(cache_file)

        cache.db_conn = await aiosqlite.connect(
            cache_file, isolation_level=None
        )
        cache.db_conn.row_factory = dict_factory

        await cache.db_conn.execute('''
            CREATE TABLE IF NOT EXISTS querycache(
                query_id TEXT PRIMARY KEY,
                data TEXT,
                expires INTEGER
            ) STRICT
        ''')

        await cache.db_conn.commit()

        return cache

    async def close(self):
        '''
        Closes the database connection
        '''

        await self.db_conn.close()

    async def exists(self, key: str) -> bool:
        '''
        Checks if a key exists in the cache
        '''

        rows = await self.db_conn.execute_fetchall(
            'SELECT * FROM querycache WHERE query_id = :query_id',
            {'query_id': str(key)}
        )

        return len(rows) > 0

    async def get(self, key: str) -> object:
        '''
        Gets the values for a key from the cache
        '''
        rows = await self.db_conn.execute_fetchall(
            'SELECT * FROM querycache WHERE query_id = :query_id',
            {'query_id': str(key)}
        )

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
            now = datetime.now(tz=timezone.utc)
            expires = now + timedelta(seconds=expiration)

            result = await self.db_conn.execute(
                'INSERT INTO querycache VALUES (:key, :value, :expiration)',
                {
                    'key': key,
                    'value': orjson.dumps(value).decode('utf-8'),
                    'expiration': int(expires.timestamp())
                }
            )
        except aiosqlite.IntegrityError as exc:
            _LOGGER.debug(f'Inserting key {key} failed primary key: {exc}')
            return False

        return result.rowcount == 1

    async def delete(self, key: str | UUID) -> bool:
        try:
            result = await self.db_conn.execute(
                'DELETE FROM querycache WHERE query_id = :key',
                {'key': key}
            )
        except Exception as exc:
            _LOGGER.debug(f'Deleting key {key} failed: {exc}')
            return False

        return result.rowcount > 0

    async def purge(self) -> int:
        '''
        Purges all expired keys from the cache
        '''

        now = datetime.now(tz=timezone.utc)
        try:
            result = await self.db_conn.execute(
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
