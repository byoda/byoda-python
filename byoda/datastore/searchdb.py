'''
Class SearchDB stores information about assets for the Service that pods can
searchs using APIs exposed by the service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from uuid import UUID
from enum import Enum
from typing import Tuple, List

from byoda.datamodel.service import Service

from byoda.datatypes import CacheTech

from byoda.datacache.kv_cache import KVCache

_LOGGER = logging.getLogger(__name__)


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

    def __init__(self, connection_string: str, service: Service):
        '''
        Initializes the DB. The DB consists of both a list of member_ids,
        a hash of the metadata for each member_id and a hash of the actual
        data for the member
        '''

        self.kvcache = KVCache.create(
            connection_string, identifier=service.service_id,
            cache_tech=CacheTech.REDIS
        )
        self.service_id: int = service.service_id

    def get_key(self, keyword: str, tracker: Tracker) -> str:
        key = f'{tracker.value}-{keyword}'
        return key

    def get_counter_key(self, key: str) -> str:
        return f'{key}-counter'

    def exists(self, keyword: str, tracker: Tracker) -> bool:
        return self.kvcache.exists(self.get_key(keyword, tracker))

    def get_list(self, keyword: str, tracker: Tracker) -> List[Tuple[UUID, str]]:
        key = self.get_key(keyword, tracker)
        data = self.kvcache.get_list(key)

        results = []

        for value in data:
            member_id, asset_id = value.decode('utf-8').split(':')
            results.append((UUID(member_id), asset_id))

        return results

    def create_append(self, keyword: str, member_id: UUID,
                      asset_id: str, tracker: Tracker) -> int:
        key = self.get_key(keyword, tracker)

        self.kvcache.push(key, f'{member_id}:{asset_id}')

        counter_key = self.get_counter_key(key)

        value = self.kvcache.incr(counter_key)

        return int(value)

    def erase_from_list(self, keyword: str, member_id: UUID, asset_id: str,
                        tracker: Tracker) -> int:
        '''
        Erases element from a list

        :returns: number of items removed from the list
        '''

        key = self.get_key(keyword, tracker)

        result = self.kvcache.remove_from_list(key, f'{member_id}:{asset_id}')

        _LOGGER.debug(f'Removed {result} items from list {key}')

        counter_key = self.get_counter_key(key)

        value = self.kvcache.decr(counter_key, amount=result)

        return value

    def delete(self, keyword: str, tracker: Tracker) -> bool:
        key = self.get_key(keyword, tracker)

        return self.kvcache.delete(key)

    def delete_counter(self, keyword: str, tracker: Tracker) -> bool:
        key = self.get_key(keyword, tracker)

        counter_key = self.get_counter_key(key)

        return self.kvcache.delete(counter_key)