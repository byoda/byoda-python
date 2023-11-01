'''
Class Asset tracks assets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''


from uuid import UUID
from typing import Self
from typing import TypeVar
from logging import getLogger
from datetime import datetime
from datetime import timezone

from byoda.datamodel.dataclass import SchemaDataObject

from byoda.datatypes import CacheTech

from byoda.datacache.om_redis import OMRedis

from byoda.util.logger import Logger

from svcserver.asset_model import Asset

_LOGGER: Logger = getLogger(__name__)

Member = TypeVar('Member')


class AssetCache:
    def __init__(self, service_id: int,
                 cache_tech: CacheTech = CacheTech.REDIS):
        '''
        Do not use this constructor, use the AssetCache.setup() factory instead
        :param service_id: the service_id of the service that we are running
        :param cache_tech: only CacheTech.REDIS is implemented
        :returns: self
        :raises: (none)
        '''
        self.service_id: int = service_id
        self.cache_tech: CacheTech = cache_tech

        self.backend: OMRedis

    @staticmethod
    async def setup(connection_string: str, service_id: int,
                    cache_tech: CacheTech = CacheTech.REDIS) -> Self:
        '''
        Factory for AssetCache

        :param connection_string: connection string for Redis server
        :param service_id: the service_id of the service that we are running
        :param cache_tech: only CacheTech.REDIS is implemented
        '''

        self = AssetCache(service_id, cache_tech=cache_tech)

        if cache_tech == CacheTech.SQLITE:
            raise NotImplementedError('AssetCache not implemented for SQLITE')
        elif cache_tech == CacheTech.REDIS:
            from .kv_redis import KVRedis
            self.backend = KVRedis(connection_string, identifier=service_id)
        else:
            raise NotImplementedError(
                f'AssetCache not implemented for {cache_tech.value}'
            )

        return self

    async def close(self):
        await self.backend.close()

    async def exists(self, asset_id: str) -> bool:
        '''
        Checks whether the query_id exists in the cache
        '''

        return await self.backend.exists(str(asset_id))

    async def set_latest_timestamp(self, member_id: UUID, timestamp: datetime):
        '''
        Sets the timestamp of the most recent created_timestmap of an asset of
        the member. We use this to do catch-up queries for assets that
        the member added since we established the websocket UPDATES connection
        to the pod of the member. Any existing timestamp in the cache
        will only be updated if

        :param member_id: the member_id of the member
        :param timestamp: the timestamp of the most recent created_timestamp
        '''

    async def set(self, asset_id: UUID, member_id: UUID,
                  data_class: SchemaDataObject,
                  value: dict[str, object]) -> bool:
        '''
        Sets the query_id in the cache

        :returns: True if the query_id was set, False if it already existed
        '''

        cursor: str = data_class.get_cursor_hash(value)
        timestamp: float = datetime.now(tz=timezone.utc).timestamp()

        data: dict[str, dict[str, object]] = {
            'meta': {
                'last_modified': timestamp,
                'cursor': cursor,
                'member_id': str(member_id),
            },
            'data': value
        }
        return await self.backend.set(str(asset_id), data)

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
