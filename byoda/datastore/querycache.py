'''
Class QueryCache tracks the query IDs from GraphQL queries to prevent
the pod from forwarding loops; executing and forwarding the same query twice

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
from uuid import UUID

from byoda.datatypes import CacheTech
from byoda.datacache.kv_cache import KVCache

_LOGGER = logging.getLogger(__name__)


class QueryCache:
    def __init__(self, connection_string: str, member_id: UUID,
                 cache_tech: CacheTech):

        self.kvcache: KVCache = KVCache.create(
            connection_string, identifier=str(member_id),
            cache_tech=cache_tech
        )

    def check_query_id(self, query_id: UUID, add: bool = True) -> bool:
        pass
