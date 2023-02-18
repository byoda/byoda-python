'''
The KV Redis data cache provides ephemeral data storage, such as services
storing data about their members

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
from uuid import UUID

import orjson

import aiosqlite

from .kv_cache import KVCache

_LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_EXPIRATION = 60 * 60 * 24 * 7  # 7 days


class KVSqlite(KVCache):
    def __init__(self, cache_file: str):
        '''
        Constructor

        :param cache_file: full path to the Sqlite DB file
        :param identifier: not used
        '''

        super().__init__(identifier=None)
        self.default_cache_expiration = DEFAULT_CACHE_EXPIRATION

    async def setup(cache_file):
        cache = KVSqlite(cache_file)

        cache.db_conn = await aiosqlite.connect(
            cache_file, isolation_level=None
        )
        cache.db_conn.row_factory = aiosqlite.Row

        await cache.db_conn.execute('''
            CREATE TABLE IF NOT EXISTS querycache(
                query_id TEXT PRIMARY KEY,
                data TEXT,
                expires INTEGER,
            ) STRICT
        ''')

        await cache.db_conn.commit()

    async def close(self):
        '''
        Closes the database connection
        '''

        self.db_conn.close()

    async def exists(self, key: str) -> bool:
        '''
        Checks if a key exists in the cache
        '''

        rows = await self.db_conn.execute_fetchall(
            'SELECT * FROM querycache WHERE query_id = ?',
            {'query_id': str(key)}
        )

        return len(rows) > 0

    async def get(self, key: str) -> object:
        '''
        Gets the values for a key from the cache
        '''
        rows = await self.db_conn.execute_fetchall(
            'SELECT * FROM querycache WHERE query_id = ?',
            {'query_id': str(key)}
        )

        if len(rows) > 1:
            raise ValueError(f'More than 1 row returned for key: {key}')

        if len(rows) == 0:
            return None

        data = orjson.dumps(rows[0])
        return data

    async def set(self, key: str, value: object,
                  expiration: int = DEFAULT_CACHE_EXPIRATION) -> bool:
        '''
        Sets the key with values in the cache. The value with be serialized
        for storage in

        :params
        :returns: True if the key was set, False otherwise
        '''

        try:
            result = self.db_conn.execute(
                'INSERT INTO querycache VALUES (?, ?, ?)',
                key, orjson.dumps(value), expiration
            )
        except Exception as exc:
            _LOGGER.debug(
                f'Inserting key {key} failed: {exc}', key=key, exc=exc
            )
            return False

        return True



    def delete(self, key: str | UUID) -> bool:
        pass
