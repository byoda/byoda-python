'''
Class CounterCache tracks the query IDs from Data API queries to prevent
the pod from forwarding loops; executing and forwarding the same query twice

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger

from byoda.datamodel.table import Table

from byoda.datatypes import CacheTech
from byoda.datatypes import CacheType
from byoda.datatypes import CounterFilter

from byoda.datacache.kv_cache import KVCache

from byoda.util.paths import Paths

_LOGGER: Logger = getLogger(__name__)

Member = TypeVar('Member')


class CounterCache:
    def __init__(self, member: Member, cache_tech: CacheTech):
        self.member: Member = member
        self.cache_tech: CacheTech = cache_tech

        if cache_tech == CacheTech.SQLITE:
            paths: Paths = member.paths
            self.filepath: str = (
                paths.root_directory + '/' +
                paths.get(paths.MEMBER_DATA_DIR, member_id=member.member_id)
                + '/' +
                paths.get(
                    paths.MEMBER_COUNTER_CACHE_FILE, member_id=member.member_id
                )
            )
        else:
            raise NotImplementedError(
                'CounterCache only implemented for Sqlite'
            )

        self.backend: KVCache | None = None

    @staticmethod
    async def create(member: Member, cache_tech=CacheTech.SQLITE):
        '''
        Factory for QueryCache

        :param connection_string: connection string for Redis server or
        path to the file for Sqlite
        :param member_id: the member ID for the membership for which the
        cache is created
        '''

        cache = CounterCache(member, cache_tech=cache_tech)

        _LOGGER.debug(f'Creating counter cache using {cache.filepath}')
        cache.backend = await KVCache.create(
            cache.filepath, cache_tech=cache_tech, cache_type=CacheType.COUNTER
        )

        return cache

    async def close(self):
        await self.backend.close()

    @staticmethod
    def get_key_name(class_name: str,
                     counter_filter: CounterFilter | None = None):
        '''
        Gets the key name for the counter cache, including the field_names
        and values if provided.
        '''

        key = class_name

        specifiers = []
        if counter_filter:
            for field_name, value in counter_filter.items():
                specifiers.append(f'{field_name}={str(value)}')

            for specifier in sorted(specifiers):
                key += f'_{specifier}'

        return key

    async def exists(self, class_name: str) -> bool:
        '''
        Checks whether the query_id exists in the cache
        '''

        return await self.backend.exists(class_name)

    async def get(self, class_name: str,
                  counter_filter: CounterFilter | None = None,
                  table: Table = None
                  ) -> int:
        '''
        Checks whether the query_id exists in the cache. If
        the table parameter is provided and the counter does
        not yet exist in the cache then the counter is
        set in the cache by reading from the table.

        :param class_name: The name of the class to get the counter for
        :param counter_filter: filter used to determine the name
        of the key in the cache
        :param table: if there is no value in the cache then get
        the value by scanning the table and write the value to the
        cache
        '''

        key = self.get_key_name(class_name, counter_filter)

        counter = await self.backend.get(key)

        if counter is None and table:
            counter = await table.count(counter_filter)
            await self.set(key, counter)

        return counter

    async def update(self, key: str, delta: int, table: Table,
                     counter_filter: CounterFilter | None = None) -> int:
        '''
        Updates the counter with the delta. If no value is
        found in the cache, the counter is set to the number
        of items in the table.

        :param delta: the delta to add to the counter, can be
        a negative number to decrement the counter
        :param table: instance of a class derived from Table
        :returns: The value of the updated counter
        '''

        counter = await self.incr(key, delta)
        if counter is None:
            counter = await table.count(counter_filter)
            await self.set(key, counter)

        return counter

    async def set(self, class_name: str, value: object) -> bool:
        '''
        Sets the query_id in the cache

        :returns: True if the query_id was set, False if it already existed
        '''

        return await self.backend.set(class_name, value)

    async def incr(self, class_name, value: int = 1) -> int:
        '''
        Increments the counter and returns the new value
        '''

        return await self.backend.incr(class_name, value)

    async def decr(self, class_name, value: int = 1) -> None:
        '''
        Increments the counter
        '''

        return await self.backend.decr(class_name, value)

    async def delete(self, class_name: str, field_name: str = None,
                     value: str | UUID = None) -> bool:
        '''
        Deletes the query_id from the cache

        :returns: True if the query_id was deleted, False if it did not exist
        '''

        key = CounterCache.get_key_name(class_name, field_name, value)

        return await self.backend.delete(key)

    async def purge(self) -> int:
        '''
        Purges the cache
        '''

        return await self.backend.purge()
