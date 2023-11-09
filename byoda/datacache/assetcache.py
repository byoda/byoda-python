'''
Asset Cache maintains lists of assets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

from uuid import UUID
from typing import Self
from typing import TypeVar
from types import ModuleType
from logging import getLogger
from datetime import datetime
from datetime import timezone
from dataclasses import dataclass

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema

from byoda.datatypes import DataRequestType
from byoda.datatypes import CacheTech

from byoda.datacache.kv_cache import KVCache

from byoda.secrets.service_secret import ServiceSecret

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)

Member = TypeVar('Member')

AssetType = TypeVar('AssetType')


@dataclass
class AssetCacheItem:
    data: AssetType
    member_id: UUID
    expires: float
    cursor: str


class AssetCache:
    '''
    AssetCache contains two functionalities:

    - Maintaining lists of assets, lists could be 'For you',
    'Recently uploaded', 'ball sports', etc. This class has
    functions to add assets to the begin of a list and to renew or expire
    assets from the list
    - Simple cache of asset with keys 'list_name:member_id:asset_id' to
    check whether an asset might be in a list. There is no guarantee that
    the cache of the assets remains up to date, so it is only used to
    prevent duplicate assets, even if it means an asset is no longer
    in a list because it was expired.
    '''

    def __init__(self, service: Service, asset_class: str,
                 expiration_window: float, cache_tech: CacheTech):
        '''
        Do not use this constructor, use the AssetCache.setup() factory instead

        :param service: The service running this cache
        :param asset_class: the data class to cache
        :param expiration_window: the number of seconds before an item expires
        :param cache_tech: only CacheTech.REDIS is implemented
        :returns: self
        :raises: (none)
        '''

        schema: Schema = service.schema
        self.service_id: int = service.service_id
        self.schema_version: int = service.schema.version

        self.tls_secret: ServiceSecret = service.tls_secret
        self.asset_class: str = asset_class
        self.expiration_window: float = expiration_window
        self.cache_tech: CacheTech = cache_tech

        network: Network = service.network
        self.network_name = network.name

        self.key: str = 'AssetCache'

        self.backend: KVCache

        module: ModuleType = schema.get_module()
        asset_class = module.asset
        self.asset_class: AssetType = asset_class

    @staticmethod
    async def setup(connection_string: str, service: Service,
                    asset_class: str, expiration_window: int,
                    cache_tech: CacheTech = CacheTech.REDIS) -> Self:
        '''
        Factory for AssetCache

        :param connection_string: connection string for Redis server
        :param service_id: the service_id of the service that we are running
        :param cache_tech: only CacheTech.REDIS is implemented
        '''

        self = AssetCache(
            service, asset_class, expiration_window, cache_tech=cache_tech
        )

        if cache_tech == CacheTech.SQLITE:
            raise NotImplementedError('AssetCache not implemented for SQLITE')
        elif cache_tech == CacheTech.REDIS:
            from .kv_redis import KVRedis
            self.backend = await KVRedis.setup(
                connection_string=connection_string,
                identifier=f'Service-{self.service_id}:'
            )
        else:
            raise NotImplementedError(
                f'AssetCache not implemented for {cache_tech.value}'
            )

        # if not self.json_exists(self.key):
        #     self.create_json_list()
        return self

    async def close(self):
        await self.backend.close()

    def json_key(self, name: str) -> str:
        return f'{self.key}:AssetList:{name}'

    async def exists_list(self, list_name: str) -> int:
        '''
        Checks whether the list exists in the cache
        '''

        return await self.backend.exists_json_list(self.json_key(list_name))

    async def create_list(self, list_name: str, data: list = []) -> bool:
        '''
        Creates a JSON list for the specified key

        :param key: the name of the list
        '''

        return await self.backend.create_json_list(
            self.json_key(list_name), data
        )

    async def delete_list(self, list_name: str) -> bool:
        '''
        Deletes the query_id from the cache

        :returns: True if the query_id was deleted, False if it did not exist
        '''

        while True:
            item: AssetCacheItem = await self.backend.rpop_json_list(
                self.json_key(list_name)
            )
            if not item:
                break

            asset_id: UUID = item['data']['asset_id']
            member_id = item['member_id']
            await self.delete_asset_from_cache(list_name, member_id, asset_id)

        result = await self.backend.delete_json_list(self.json_key(list_name))
        return bool(result)

    async def lpush(self, list_name: str, data: object | AssetType,
                    member_id: UUID, cursor: str, expires: float = None
                    ) -> int:
        '''
        Adds the data to the start of a JSON list

        :param list_name: the name of the list
        :param data: the asset to add to the list
        :param member_id: the member_id of the member that owns the asset
        :param cursor: the cursor of the asset
        :param expires: the timestamp when the asset expires
        :returns: the length of the list after the push operation
        '''

        if not isinstance(data, dict):
            data = data.model_dump()

        asset_id: UUID = data['asset_id']
        if await self.asset_exists_in_cache(list_name, member_id, asset_id):
            _LOGGER.debug(
                f'Asset {asset_id} from member {member_id} already exists in '
                'cache'
            )
            return False

        timestamp: float = datetime.now(tz=timezone.utc).timestamp()
        if not expires:
            expires = timestamp + self.expiration_window

        delay = int(expires - timestamp)
        _LOGGER.debug(
            f'Adding asset {data["asset_id"]} from member {member_id}'
            f'with expiration in {delay} seconds '
        )

        asset_item = AssetCacheItem(
            member_id=member_id,
            expires=expires,
            cursor=cursor,
            data=data
        )

        await self.add_asset_to_cache(list_name, member_id, data)

        result = await self.backend.lpush_json_list(
            self.json_key(list_name), asset_item.__dict__
        )

        if result is False:
            result = 0

        return result

    async def rpush(self, list_name: str, data: object | AssetType,
                    member_id: UUID, cursor: str, expires: float = None
                    ) -> bool:
        '''
        Adds the data to the end of a JSON list

        :param list_name: the name of the list
        :param data: the asset to add to the list
        :param member_id: the member_id of the member that owns the asset
        :param cursor: the cursor of the asset
        :param expires: the timestamp when the asset expires
        :returns: True if the data was added to the list
        '''

        if isinstance(data, self.asset_class):
            data = data.model_dump()

        if await self.asset_exists_in_cache(
                list_name, member_id, data['asset_id']):
            _LOGGER.debug(
                f'Asset {data["asset_id"]} from member {member_id} '
                'already exists in cache'
            )
            return False

        timestamp: float = datetime.now(tz=timezone.utc).timestamp()
        if not expires:
            expires = timestamp + self.expiration_window

        delay = int(expires - timestamp)
        _LOGGER.debug(
            f'Adding asset {data["asset_id"]} from member {member_id}'
            f'with expiration in {delay} seconds '
        )

        asset_item = AssetCacheItem(
            member_id=member_id,
            expires=expires,
            cursor=cursor,
            data=data
        )

        await self.add_asset_to_cache(list_name, member_id, data)

        return await self.backend.lpush_json_list(
            self.json_key(list_name), asset_item.__dict__
        )

    async def rpop(self, list_name: str) -> AssetCacheItem | None:
        '''
        Pops the item from the end of the list

        :param list_name: the name of the list
        :returns: the item or None if the list is empty
        '''

        data: dict = await self.backend.rpop_json_list(
            self.json_key(list_name)
        )

        if not data:
            return None

        asset_item = AssetCacheItem(**data)
        asset_item.data = self.asset_class(**asset_item.data)

        member_id: UUID = asset_item.member_id
        asset_id: UUID = asset_item.data.asset_id

        await self.delete_asset_from_cache(list_name, member_id, asset_id)

        return asset_item

    async def get_range(self, list_name: str, start: int = 0, end: int = -1
                        ) -> list[AssetCacheItem]:

        '''
        Gets a list of items from the cache

        :returns: list of items
        '''

        data: list[AssetCacheItem] = await self.backend.json_range(
            self.json_key(list_name), start, end
        )

        if data:
            results = []
            for data_item in data:
                asset_item = AssetCacheItem(**data_item)
                asset_item.data = self.asset_class(**asset_item.data)
                results.append(asset_item)
            return results

        return []

    async def len(self, list_name: str) -> int:
        '''
        Gets the length of a JSON list

        :param key: the name of the list
        :returns: the length of the list
        '''

        return await self.backend.json_len(self.json_key(list_name))

    async def get(self, list_name: str, pos: int = 0) -> AssetCacheItem | None:
        '''
        Gets a single item from the cache

        :returns: item
        '''

        result = await self.get_range(list_name, pos, pos + 1)

        if len(result) == 1:
            return result[0]

        return None

    @staticmethod
    def get_asset_key(list_name: str, member_id: UUID | str,
                      asset_id: UUID | str) -> str:
        '''
        Get key for the asset in the cache

        :param list_name: the name of the list to check
        :param member_id: the member_id of the member that owns the asset
        :param asset_id: the asset_id of the asset
        :returns: str
        :raises: (none)
        '''

        return f'AssetCache:{list_name}:Asset:{member_id}:{asset_id}'

    async def asset_exists_in_cache(self, list_name: str,
                                    member_id: UUID | str,
                                    asset_id: UUID | str) -> bool:
        '''
        Checks whether an asset is in the cache

        :param list_name: the name of the list to check
        :param member_id: the member_id of the member that owns the asset
        :param asset_id: the asset_id of the asset
        :returns: str
        :raises: (none)
        '''

        key: str = AssetCache.get_asset_key(list_name, member_id, asset_id)

        return await self.backend.exists(key)

    async def add_asset_to_cache(self, list_name: str, member_id: UUID | str,
                                 asset_data: dict[str, object]) -> bool:
        '''
        Adds an asset to the cache

        :param list_name: the name of the list to check
        :param member_id: the member_id of the member that owns the asset
        :param asset_id: the asset_id of the asset
        :returns: str
        :raises: (none)
        '''

        asset_id: UUID | str = asset_data['asset_id']
        key = AssetCache.get_asset_key(list_name, member_id, asset_id)

        return await self.backend.set(key, asset_data)

    async def delete_asset_from_cache(self, list_name: str,
                                      member_id: UUID | str,
                                      asset_id: UUID | str) -> bool:
        '''
        Deletes asset from the cache

        :param list_name: the name of the list to check
        :param member_id: the member_id of the member that owns the asset
        :param asset_id: the asset_id of the asset
        :returns: str
        :raises: (none)
        '''

        key: str = AssetCache.get_asset_key(list_name, member_id, asset_id)

        return await self.backend.delete(key)

    async def expire(self, list_name: str,
                     timestamp: datetime | int | float = None,
                     ) -> tuple[int, int]:
        '''
        Expires items in the cache.

        In this class, we are pushing new items to the front of the list,
        the list is ordered from newest to oldest. We are using this by
        starting expiring things from the end of the list moving forward
        until we find an item that has not yet expired.

        We remove items from the end of the list, and if we can renew
        it then we add it to a temporary list. Once we have found an
        item that has not expired yet or we have emptied the list, we
        add back items that were expired but that we were able to
        refresh

        :param list_name: the name of the list
        :param timestamp: the timestamp before which items should be expired
        :param tls_secret: the TLS secret to use when calling members
        to see if the asset still exists
        :returns: tuple with the number of items expired and the number of
        items renewed
        '''

        if not timestamp:
            timestamp = datetime.now(tz=timezone.utc).timestamp()
        elif isinstance(timestamp, datetime):
            timestamp = timestamp.timestamp()

        items_expired: int = 0
        items_renewed: int = 0
        cache_items: list[dict] = []

        while True:
            count = await self.len(list_name)
            if count == 0:
                break

            cache_item: AssetCacheItem = await self.rpop(list_name)
            if cache_item.expires > timestamp:
                _LOGGER.debug(
                    f'Found asset {cache_item.data.asset_id} from '
                    f'member {cache_item.member_id} that '
                    f'expiring at {cache_item.expires}, '
                    'so it has not expired yet'
                )
                cache_items.append(cache_item)
                # This item did not expire but we are re-adding
                # it back to the list so we don't want this asset
                # to be counted as renewed
                items_renewed -= 1
                break

            refreshed_asset: AssetType | None = None
            try:
                member_id: UUID = cache_item.member_id
                asset: AssetType = cache_item.data
                asset_id: UUID = asset.asset_id

                if str(member_id).startswith('aaaaaaaa'):
                    _LOGGER.debug('Not attempting to renew test asset')
                else:
                    refreshed_asset = await self._refresh_asset(
                        member_id, asset_id
                    )
                    cache_items.append(refreshed_asset)
            except FileNotFoundError:
                _LOGGER.debug(
                    f'Member {member_id} no longer stores '
                    f'asset {asset_id}'
                )
                await self.delete_asset_from_cache(
                    list_name, member_id, asset_id
                )
            except Exception as exc:
                _LOGGER.debug(
                    f'Unable to renew cached asset {asset_id} '
                    f'from member {member_id}: {exc}')

            if not refreshed_asset:
                items_expired += 1

        # now we add refreshed assets back to the list,
        # making sure we descend in age of the assets

        for refreshed_asset in reversed(cache_items):
            await self.rpush(
                list_name, refreshed_asset.data, refreshed_asset.member_id,
                refreshed_asset.cursor, refreshed_asset.expires
            )
            items_renewed += 1

        return items_expired, items_renewed

    async def _refresh_asset(self, member_id: UUID, asset_id: UUID
                             ) -> AssetCacheItem:
        '''
        Renews an asset in the cache

        :param member_id: the member_id of the member that owns the asset
        :param asset_id: the asset_id of the asset to renew
        :param tls_secret: the TLS secret to use when calling members
        to see if the asset still exists
        :returns: the renewed asset
        '''

        resp = await self._asset_query(member_id, asset_id)

        if resp.status_code != 200:
            raise FileNotFoundError

        data = resp.json()

        if not data or data['total_count'] == 0:
            raise FileNotFoundError

        if data['total_count'] > 1:
            _LOGGER.debug(
                f'Multiple assets found for asset_id {asset_id} '
                f'from member {member_id}, using only the first one'
            )

        node: dict[str, object] = data['edges'][0]['node']
        timestamp: float = datetime.now(tz=timezone.utc).timestamp()
        asset = AssetCacheItem(
            member_id=member_id,
            expires=timestamp + self.expiration_window,
            cursor=data['edges'][0]['cursor'],
            data=self.asset_class(**node)
        )

        return asset

    async def _asset_query(self, member_id: UUID, asset_id: UUID = None,
                           ) -> HttpResponse:
        '''
        Queries the data API of a memberfor an asset

        :param asset_class: the asset class to query
        :param asset_id: the asset_id of the asset to query
        :param tls_secret: the TLS secret to use when calling members
        to see if the asset still exists
        :returns: the asset
        '''

        data_filter: dict[str, dict[str, object]] | None = None
        if asset_id:
            data_filter: dict = {'asset_id': {'eq': asset_id}}

        resp: HttpResponse = await DataApiClient.call(
            self.service_id, self.asset_class, action=DataRequestType.QUERY,
            secret=self.tls_secret, network=self.network_name,
            member_id=member_id, data_filter=data_filter, first=1,
        )

        return resp
