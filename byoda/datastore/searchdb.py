'''
Class SearchDB stores information about assets for the Service that pods can
searchs using APIs exposed by the service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from enum import Enum
from logging import getLogger
from byoda.util.logger import Logger

from byoda.datamodel.service import Service

from byoda.datatypes import CacheTech
from byoda.datatypes import CacheType

from byoda.datacache.kv_cache import KVCache

_LOGGER: Logger = getLogger(__name__)


class Tracker(Enum):
    MENTION = 'MENTION'
    HASHTAG = 'HASHTAG'


class SearchDB:
    MENTION_KEY_FORMAT = 'MENTION-{mention}'
    HASHTAG_KEY_FORMAT = 'HASHTAG-{hashtag}'
    KEY_PREFIX = 'service-{namespace}'
    TWITTER_CACHE_EXPIRATION = 365 * 24 * 60 * 60

    '''
    Store for searchable data for assets available from pods
    '''

    def __init__(self, service: Service):
        '''
        Do not call this constructor directly. Use SearchDB.setup() instead
        '''

        self.kvcache: KVCache | None = None
        self.service_id: int = service.service_id

    async def setup(connection_string: str, service: Service):
        '''
        Factory for the SearchDB class

        :param connection_str: connection string for Redis server
        :param service: the service for which the search database is created
        :returns: SearchDB instance
        :raises:
        '''

        self = SearchDB(service)
        self.kvcache = await KVCache.create(
            connection_string, service_id=service.service_id,
            network_name=service.network.name, server_type='ServiceServer',
            cache_type=CacheType.SEARCHDB, cache_tech=CacheTech.REDIS
        )

        return self

    def get_key(self, keyword: str, tracker: Tracker) -> str:
        key = f'{tracker.value}-{keyword}'
        return key

    def get_counter_key(self, key: str) -> str:
        return f'{key}-counter'

    async def exists(self, keyword: str, tracker: Tracker) -> bool:
        return await self.kvcache.exists(self.get_key(keyword, tracker))

    async def get_list(self, keyword: str, tracker: Tracker
                       ) -> list[tuple[UUID, str]]:
        key = self.get_key(keyword, tracker)
        data = await self.kvcache.get_list(key)

        results = []

        for value in data:
            member_id, asset_id = value.decode('utf-8').split(':')
            results.append((UUID(member_id), asset_id))

        return results

    async def create_append(self, keyword: str, member_id: UUID,
                            asset_id: str, tracker: Tracker) -> int:
        key = self.get_key(keyword, tracker)

        await self.kvcache.push(key, f'{member_id}:{asset_id}')

        counter_key = self.get_counter_key(key)

        value = await self.kvcache.incr(counter_key)

        return int(value)

    async def erase_from_list(self, keyword: str, member_id: UUID,
                              asset_id: str, tracker: Tracker) -> int:
        '''
        Erases element from a list

        :returns: number of items removed from the list
        '''

        key = self.get_key(keyword, tracker)

        result = await self.kvcache.remove_from_list(
            key, f'{member_id}:{asset_id}'
        )

        _LOGGER.debug(f'Removed {result} items from list {key}')

        counter_key = self.get_counter_key(key)

        value = await self.kvcache.decr(counter_key, amount=result)

        return value

    async def delete(self, keyword: str, tracker: Tracker) -> bool:
        key = self.get_key(keyword, tracker)

        return await self.kvcache.delete(key)

    async def delete_counter(self, keyword: str, tracker: Tracker) -> bool:
        key = self.get_key(keyword, tracker)

        counter_key = self.get_counter_key(key)

        return await self.kvcache.delete(counter_key)
