'''
Class QueryCache tracks the query IDs from GraphQL queries to prevent
the pod from forwarding loops; executing and forwarding the same query twice

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from uuid import UUID
from typing import TypeVar

from byoda.datamodel.table import Table

from byoda.datatypes import CacheTech
from byoda.datatypes import CacheType

from byoda.datacache.kv_cache import KVCache

from byoda.util.paths import Paths

_LOGGER = logging.getLogger(__name__)

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
        cache.backend: KVCache = await KVCache.create_async(
            cache.filepath, identifier=str(member.member_id),
            cache_tech=cache_tech, cache_type=CacheType.COUNTER
        )

        return cache

    async def close(self):
        await self.backend.close()

    @staticmethod
    def _get_key_name(class_name: str, field_name: str = None,
                      value: any = None):
        if field_name is None:
            return class_name
        else:
            return f'{class_name}-{field_name}-{str(value)}'

    async def exists(self, class_name: str) -> bool:
        '''
        Checks whether the query_id exists in the cache
        '''

        return await self.backend.exists(class_name)

    async def get(self, class_name: str) -> bool:
        '''
        Checks whether the query_id exists in the cache
        '''

        return await self.backend.get(class_name)

    async def update(self, delta: int, table: Table, field_name: str = None,
                     value: any = None) -> int:
        '''
        Updates the counter with the delta. If no value is
        found in the cache, the counter is set to the number
        of items in the table.

        :param delta: the delta to add to the counter, can be
        a negative number to decrement the counter
        :param table: instance of a class derived from Table
        :returns: The value of the updated counter
        '''

        if (field_name and value is None) or (field_name is None and value):
            raise ValueError(
                'Both field_name and value must be specified or both None'
            )

        key = CounterCache._get_key_name(table.class_name, field_name, value)

        counter = await self.incr(key, delta)
        if counter is None:
            counter = await table.count(field_name, value)
            await self.set(table.class_name, counter)

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

        key = CounterCache._get_key_name(class_name, field_name, value)

        return await self.backend.delete(key)

    async def purge(self) -> int:
        '''
        Purges the cache
        '''

        return await self.backend.purge()
