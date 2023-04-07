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

from byoda.datatypes import CacheTech
from byoda.datatypes import CacheType

from byoda.datacache.kv_cache import KVCache

from byoda.util.paths import Paths

_LOGGER = logging.getLogger(__name__)

Member = TypeVar('Member')


class QueryCache:
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
                    paths.MEMBER_QUERY_CACHE_FILE, member_id=member.member_id
                )
            )
        else:
            raise NotImplementedError('QueryCache not implemented for REDIS')

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

        cache = QueryCache(member, cache_tech=cache_tech)
        _LOGGER.debug(f'Creating query cache using {cache.filepath}')
        cache.backend: KVCache = await KVCache.create_async(
            cache.filepath, identifier=str(member.member_id),
            cache_tech=cache_tech, cache_type=CacheType.QUERY_ID
        )

        return cache

    async def close(self):
        await self.backend.close()

    async def exists(self, query_id: str) -> bool:
        '''
        Checks whether the query_id exists in the cache
        '''

        return await self.backend.exists(str(query_id))

    async def set(self, query_id: UUID, value: object) -> bool:
        '''
        Sets the query_id in the cache

        :returns: True if the query_id was set, False if it already existed
        '''

        return await self.backend.set(str(query_id), value)

    async def delete(self, query_id: UUID) -> bool:
        '''
        Deletes the query_id from the cache

        :returns: True if the query_id was deleted, False if it did not exist
        '''

        return await self.backend.delete(str(query_id))

    async def purge(self) -> int:
        '''
        Purges the cache
        '''

        return await self.backend.purge()
