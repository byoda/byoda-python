'''
Asset Cache maintains lists of assets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from uuid import UUID
from typing import Self
from typing import TypeVar
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from fastapi.encoders import jsonable_encoder

from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.datamodel.metrics import Metrics

from byoda.datatypes import IngestStatus
from byoda.datatypes import DataRequestType

from byoda.models.data_api_models import EdgeResponse as Edge
from byoda.models.data_api_models import Asset

from byoda.datacache.channel_cache import ChannelCache

from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.service_secret import ServiceSecret

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda.datacache.searchable_cache import SearchableCache

from byoda import config

from .asset_list import AssetList


_LOGGER: Logger = getLogger(__name__)


Member = TypeVar('Member')

AssetType = TypeVar('AssetType')


class AssetCache(SearchableCache, Metrics):
    LUA_FUNCTIONS_FILE: str = 'byotubesvr/redis.lua'
    DEFAULT_ASSET_LIST: str = 'recent_uploads'
    DEFAULT_ASSET_EXPIRATION: int = 60 * 60 * 24 * 3  # 3 days
    # The worker stores here all the lists that have been generated
    # based on the assets it has collected.
    # This list used to refresh assets in the cache. The list is
    LIST_OF_LISTS_KEY: str = 'list_of_lists'
    # ordered from newest to oldest asset in the cache
    # Threshold for adding assets to the 'recent_uploads' list
    RECENT_THRESHOLD: timedelta = timedelta(days=7)

    '''
    Stores assets in a cache and provides methods to search for them.
    '''

    def __init__(self, connection_string: str) -> None:
        '''
        Initialize the AssetCache class.

        :param connection_string: The connection string to the Redis server.
        :return: None
        :raises: None
        '''

        super().__init__(connection_string)

    @staticmethod
    async def setup(connection_string: str,
                    lua_functions_file: str = LUA_FUNCTIONS_FILE) -> Self:
        '''
        Setup the cache and return an instance.

        :param connection_string: The connection string to the Redis server.
        :return: An instance of the AssetCache class.
        :raises: None
        '''

        self: AssetCache = AssetCache(connection_string)
        await self.create_search_index()
        await self.load_functions(lua_functions_file)

        self.metrics_setup()

        return self

    async def add_newest_asset(
        self, member_id: UUID, asset: dict,
        expires_at: datetime | int | float | None = None
    ) -> bool:
        '''
        Add an asset to the cache.

        :param member_id: The member that originated the asset.
        :param asset: The asset to add.
        :param expiration: the timestamp at which the asset expires
        :return: bool, on whether asset was added to cache
        :raises: None
        '''

        metrics: dict[str, Gauge | Counter] = config.metrics

        asset_model: Asset = Asset(**asset)

        asset_lists: set[AssetList] = self.get_asset_lists(
            member_id, asset_model
        )

        if expires_at is None:
            expires_at = (
                datetime.now(tz=UTC).timestamp()
                + AssetCache.DEFAULT_ASSET_EXPIRATION
            )
        elif isinstance(expires_at, datetime):
            expires_at = expires_at.timestamp()

        # We override the cursor that the member may have set as that cursor
        # is only unique(-ish) for the member. We need a cursor that is unique
        # globally.
        server_cursor: str = self.get_cursor(member_id, asset_model.asset_id)

        asset_edge: Edge[Asset] = Edge[Asset](
            node=asset_model, origin=member_id, cursor=server_cursor
        )

        log_data: dict[str, any] = {
            'asset_id': asset_model.asset_id, 'member_id': member_id
        }
        if not asset_model.creator:
            _LOGGER.debug('Not adding asset with no creator', extra=log_data)
            return False

        # We replace UUIDs with strings and datetimes with timestamps. The
        # get_asset() method will cast to Pydantic model and that will return
        # the values in their proper type
        asset_data: dict[str, any] = jsonable_encoder(asset_edge)

        # We want to store timestamp as a number so people can sort and
        # filter on it
        asset_data['node']['created_timestamp'] = \
            asset_edge.node.created_timestamp.timestamp()

        asset_data['node']['published_timestamp'] = \
            asset_edge.node.published_timestamp.timestamp()

        await self.json_set(
            asset_lists, AssetCache.ASSET_KEY_PREFIX, asset_data,
            expires_in=expires_at - datetime.now(tz=UTC).timestamp()
        )

        await self.update_creators_list(member_id, asset_model.creator)

        await self.update_list_of_lists(asset_lists)
        metric: str = 'assetcache_total_lists'
        if metrics and metric in metrics:
            metrics[metric].set(len(asset_lists))

        log_data['lists'] = len(asset_lists)
        _LOGGER.debug('Added asset to cache', extra=log_data)

        return True

    def get_asset_lists(self, member_id: UUID, asset_model: Asset
                        ) -> set[AssetList]:
        '''
        The various lists that this asset should be added to

        :param member_id: The member that originated the asset.
        :param asset: The asset to add.
        :returns: set of asset lists
        '''

        list_permutations: set[str] = AssetCache.get_list_permutations(
            member_id, asset_model
        )
        asset_lists: set[AssetList] = set()
        for list_name in list_permutations:
            asset_lists.add(
                AssetList(list_name, redis=self.client)
            )

        return asset_lists

    async def in_cache(self, member_id: UUID, asset_id: UUID) -> bool:
        '''
        Check if an asset is in the cache.

        :param member_id: The member that originated the asset.
        :param asset_id: The asset to check.
        :return: True if the asset is in the cache, False otherwise.
        :raises: None
        '''

        server_cursor: str = self.get_cursor(member_id, asset_id)

        item_key: str = AssetCache.ASSET_KEY_PREFIX + server_cursor

        return await self.client.exists(item_key)

    async def get_asset_by_key(self, asset_key: str) -> Edge:
        '''
        Get an asset by its key.

        :param asset_key: The key of the asset to get.
        :return: The asset.
        :raises: None
        '''

        metrics: dict[str, Gauge | Counter] = config.metrics

        if not asset_key.startswith(AssetCache.ASSET_KEY_PREFIX):
            asset_key = AssetCache.ASSET_KEY_PREFIX + asset_key

        asset_data: any = await self.json_get(asset_key)
        metric: str
        if not asset_data:
            metric = 'assetcache_asset_not_found'
            if metrics and metric in metrics:
                metrics[metric].inc()
            raise FileNotFoundError(f'Asset not found for key: {asset_key}')

        metric = 'assetcache_asset_found'
        if metrics and metric in metrics:
            metrics[metric].inc()

        asset_data['node'] = Asset(**asset_data['node'])
        edge = Edge(**asset_data)
        return edge

    async def search(self, query: str, offset: int = 0, num: int = 10
                     ) -> list[Edge]:
        '''
        Searches for the text in the asset cache

        :param query: The query to perform
        :param first: The index of the first search result to return
        :param num: The maximum number of search results to return
        :returns: a list of assets
        '''

        data: list[dict[str, str | dict[str, any]]] = \
            await super().search(query, offset, num)

        results: list[Edge] = []
        for item in data or []:
            ingest_status: str = item['node']['ingest_status']
            if (ingest_status in (IngestStatus.EXTERNAL.value,
                                  IngestStatus.PUBLISHED.value)):
                item['node'] = Asset(**item['node'])
                results.append(Edge(**item))

        return results

    async def get_asset_expiration(self, edge: str | Edge) -> int:
        '''
        Gets the expiration time of an asset

        :param node: either the cursor of the asset to get the expiration time
        for or the edge of the asset to get the expiration time for
        :returns: the expiration time of the asset
        '''

        if isinstance(edge, Edge):
            cursor: str = self.get_cursor(edge.origin, edge.node.asset_id)
        else:
            cursor = edge

        asset_key: str = AssetCache.ASSET_KEY_PREFIX + cursor

        _LOGGER.debug('Getting asset expiration for asset key: ' + asset_key)

        return await self.get_expiration(asset_key)

    async def add_asset_to_all_assets_list(self, edge: str | Edge,
                                           expires_at: int | float) -> None:
        '''
        Adds the cursor for an asset to both the sorted set and the
        list of assets, but only if it is not in the sorted set already

        :param node:
        :param expiration: timestamp when the asset expires from the cache
        :returns: the length of the list after adding the item
        '''

        cursor: str
        if isinstance(edge, Edge):
            cursor = self.get_cursor(edge.origin, edge.node.asset_id)
        else:
            cursor = edge

        asset_key: str = cursor
        if not cursor.startswith(AssetCache.ASSET_KEY_PREFIX):
            asset_key = AssetCache.ASSET_KEY_PREFIX + cursor

        list_name: str = AssetCache.ALL_ASSETS_LIST

        oset_key: str
        oset_key = AssetList.get_key(list_name)
        if not await self.client.zrank(oset_key, asset_key):
            await self.client.zadd(oset_key, {asset_key: expires_at})

        return await self.client.zcount(oset_key, '-inf', '+inf')

    async def get_list_assets(self,
                              asset_list: str = DEFAULT_ASSET_LIST,
                              first: int = 20, after: str | None = None,
                              filter_name: str | None = None,
                              filter_value: str | None = None) -> list[Edge]:
        '''
        Get a page worth of assets from a list

        :param asset_list: the name of the list to get the assets from
        :param first: the number of assets to get
        :param after: the cursor of the asset to start from
        :param filter_name: the name of the field to filter on
        :param filter_value: the value of the field to filter on
        :returns: a list of asset edges
        '''

        _LOGGER.debug(
            'Getting list of assets', extra={
                'asset_list': asset_list,
                'first': first,
                'after': after,
                'filter_name': filter_name,
                'filter_value': filter_value
            }
        )
        data: list[dict] = await self.get_list_values(
            asset_list, AssetCache.ASSET_KEY_PREFIX, first=first, after=after,
            filter_name=filter_name, filter_value=filter_value
        )

        results: list[Edge] = []
        for item in data:
            asset: Asset = Asset(**item['node'])
            if type(asset.created_timestamp) in (int, float):
                asset.created_timestamp = \
                    datetime.fromtimestamp(asset.created_timestamp)
                asset.published_timestamp = \
                    datetime.fromtimestamp(asset.published_timestamp)
            item['node'] = asset
            results.append(Edge(**item))

        return results

    async def update_creators_list(self, member_id: UUID, creator: str
                                   ) -> None:
        '''
        Updates:
        - the expiration for the ordered set of all assets of the creator
        - the ordered set of all creators

        :param creator: The creator to add to the list of creators.
        :return: None
        :raises: None
        '''

        if not creator:
            _LOGGER.debug('No creator to add to the list of creators')

        creator_oset: str = AssetList.get_key(creator)
        await self.set_expiration(creator_oset)

        cursor: str = ChannelCache.get_cursor(member_id, creator)

        all_creators_key: str = SearchableCache.get_all_creators_key()
        log_extra: dict[str, str] = {
            'creator': creator,
            'member_id': member_id,
            'asset_key': all_creators_key,
            'cursor': cursor
        }

        _LOGGER.debug('Reviewing list of creators', extra=log_extra)
        if await self.client.zrank(all_creators_key, cursor):
            _LOGGER.debug(
                'Creator already in the set of all creators', extra=log_extra
            )
            await self.set_expiration(
                all_creators_key, AssetCache.DEFAULT_EXPIRATION_LISTS
            )
            return

        _LOGGER.debug(
            'Adding creator to the set of all creators', extra=log_extra
        )
        expires_at: float = (
            datetime.now().timestamp() + AssetCache.DEFAULT_EXPIRATION_LISTS
        )
        await self.client.zadd(all_creators_key, {cursor: expires_at})
        await self.set_expiration(
            all_creators_key, AssetCache.DEFAULT_EXPIRATION_LISTS
        )


    async def get_creators_list(self) -> set[str] | None:
        '''
        Get the list of creators.

        :return: The list of creators.
        :raises: None
        '''

        all_creators_key: str = SearchableCache.get_all_creators_key()
        creators: set[bytes] = await self.client.zrange(
            all_creators_key, 0, -1
        )

        _LOGGER.debug(
            'Found creators for set',
            {'key': all_creators_key, 'count': len(creators)}
        )
        return creators

    async def update_list_of_lists(self, asset_lists: set[AssetList]) -> None:
        '''
        Update the list of lists.

        :param lists: The lists to add to the list of lists.
        :return: None
        :raises: None
        '''

        oset_key: str
        oset_key = AssetList.get_key(AssetCache.LIST_OF_LISTS_KEY)
        items: dict[str, int] = {}
        asset_list: AssetList
        for asset_list in asset_lists:
            expires_at: float = (
                datetime.now(tz=UTC).timestamp()
                + AssetCache.DEFAULT_EXPIRATION_LISTS
            )
            items[asset_list.name] = expires_at

        await self.client.zadd(oset_key, items)

    async def get_list_of_lists(self) -> set[str] | None:
        '''
        Get the list of lists.

        :return: The list of lists.
        :raises: None
        '''

        oset_key: str
        oset_key = AssetList.get_key(AssetCache.LIST_OF_LISTS_KEY)
        lists: set[bytes] = await self.client.zrange(oset_key, 0, -1)
        return lists

    async def delete_asset_from_cache(self,  member_id: UUID | str,
                                      asset_id: UUID | str) -> bool:
        '''
        Deletes asset from the cache

        :param list_name: the name of the list to check
        :param member_id: the member_id of the member that owns the asset
        :param asset_id: the asset_id of the asset
        :returns: str
        :raises: (none)
        '''

        server_cursor: str = self.get_cursor(member_id, asset_id)
        asset_key: str = AssetCache.ASSET_KEY_PREFIX + server_cursor

        metrics: dict[str, Gauge | Counter] = config.metrics
        metric: str = 'assetcache_deleted_assets'
        if metrics and metric in metrics:
            metrics[metric].inc()

        return await self.client.delete(asset_key)

    async def refresh_asset(self, edge: Edge, asset_class_name: str,
                            tls_secret: MemberSecret | ServiceSecret
                            ) -> Edge | None:
        '''
        Renews an asset in the cache and prepends it to the list of assets

        :param member_id: the member_id of the member that owns the asset
        :param asset_id: the asset_id of the asset to renew
        :param tls_secret: the TLS secret to use when calling members
        to see if the asset still exists
        :returns: the renewed asset
        '''

        member_id: UUID = edge.origin
        node: Asset = edge.node
        asset_id: UUID = node.asset_id

        metrics: dict[str, Gauge | Counter] = config.metrics

        log_data: dict[str, any] = {
            'member_id': member_id,
            'asset_id': asset_id,
            'asset_class_name': asset_class_name
        }
        try:
            resp: HttpResponse = await self._asset_query(
                member_id, asset_id, asset_class_name, tls_secret
            )
        except Exception as exc:
            _LOGGER.debug(
                'Error calling data API of member',
                extra=log_data | {'exception': exc}
            )
            return None

        metric: str
        if resp.status_code != 200:
            metric = 'assetcache_refresh_asset_failures'
            if metrics and metric in metrics:
                metrics[metric].inc()
            return None

        data: dict[str, any] = resp.json()

        if not data or data.get('total_count') == 0:
            metric = 'assetcache_refreshable_asset_not_found'
            if metrics and metric in metrics:
                metrics[metric].inc()
            return None

        if data['total_count'] > 1:
            _LOGGER.debug(
                'Multiple assets found for asset_id from member, '
                'using only the first one',
                extra=log_data | {'total_count': data['total_count']}
            )
            metric = 'assetcache_refreshable_asset_dupes'
            if metrics and metric in metrics:
                metrics[metric].inc()

        node: dict[str, object] = data['edges'][0]['node']
        asset = Edge(
            origin=member_id,
            cursor=data['edges'][0]['cursor'],
            node=self.asset_class(**node)
        )

        return asset

    async def _asset_query(self, member_id: UUID, asset_id: UUID,
                           asset_class_name: str,
                           tls_secret: MemberSecret | ServiceSecret
                           ) -> HttpResponse:
        '''
        Queries the data API of a member for an asset

        :param asset_id: the asset_id of the asset to query
        :param tls_secret: the TLS secret to use when calling members
        to see if the asset still exists
        :returns: the asset
        '''

        metrics: dict[str, Gauge | Counter] = config.metrics

        data_filter: dict[str, dict[str, object]] | None = None
        if asset_id:
            data_filter: dict = {'asset_id': {'eq': asset_id}}

        log_data: dict[str, any] = {
            'member_id': member_id,
            'asset_id': asset_id,
            'data_filter': data_filter,
            'asset_class_name': asset_class_name
        }
        _LOGGER.debug('Calling Data API to fetch asset', extra=log_data)
        resp: HttpResponse = await DataApiClient.call(
            tls_secret.service_id, asset_class_name,
            action=DataRequestType.QUERY, secret=tls_secret,
            network=tls_secret.network, member_id=member_id,
            data_filter=data_filter, first=1,
        )

        _LOGGER.debug(
            'Data API response',
            extra=log_data | {'status_code': resp.status_code}
        )
        metric: str = 'assetcache_refresh_asset_api_calls'
        if metrics and metric in metrics:
            metrics[metric].inc()

        return resp

    @staticmethod
    def get_short_appendix(asset_model: Asset) -> str:
        '''
        Appendix for the key for a short asset
        '''

        metrics: dict[str, Gauge | Counter] = config.metrics
        metric: str
        if asset_model.duration <= 60:
            asset_model.screen_orientation_horizontal = False
            metric = 'assetcache_short_assets_added'
            if metrics and metric in metrics:
                metrics[metric].inc()
            return '-short'

        else:
            metric = 'assetcache_long_assets_added'
            if metrics and metric in metrics:
                metrics[metric].inc()

            return ''

    @staticmethod
    def get_list_permutations(member_id: UUID, asset_model: Asset,
                              max_lists: int = 32) -> set[str]:
        '''
        Generate the names of the lists that this asset should be added to

        :param asset_model: the (pydantic) asset to generate the lists for
        '''
        # We use short_append to make sure vertically oriented assets
        # go to separate lists from horizontally oriented assets.
        short_append: str = AssetCache.get_short_appendix(asset_model)

        log_data: dict[str, any] = {
            'short_append': short_append,
            'member_id': member_id,
            'asset_id': asset_model.asset_id,
            'creator': asset_model.creator,
        }
        lists_set: set[str] = set()

        categories: list[str] | None = sorted(
            [
                category.lower() for category in asset_model.categories
                if isinstance(category, str)
            ]
        )[:2]

        keywords: list[str] = sorted(
            [
                keyword.lower() for keyword in asset_model.keywords
                if isinstance(keyword, str)
            ]
        )[:4]

        annotations: list[str] = sorted(
            [
                annotation.lower() for annotation in asset_model.annotations
                if isinstance(annotation, str)
            ]
        )[:4]

        # Create the lists that we will add the asset to.
        # Structure is: <category>-<keyword>-<annotation>-<short>
        category: str
        keyword: str
        annotation: str
        for category in categories:
            list_name: str = category + short_append
            lists_set.add(list_name)

            for keyword in keywords:
                list_name: str = category + '-' + keyword + short_append
                lists_set.add(list_name)

                for annotation in annotations:
                    list_name = (
                        category + '-' + keyword + '-' + annotation +
                        short_append
                    )
                    lists_set.add(list_name)

        # We don't want too many lists
        list_permutations: int = max_lists - 2
        if len(lists_set) > list_permutations:
            lists_set = set((list(lists_set))[:list_permutations])

        # Add the asset to the list for the creator
        if asset_model.creator:
            lists_set.add(f'{member_id}_{asset_model.creator}{short_append}')
        else:
            _LOGGER.debug('No creator for asset', extra=log_data)

        created_since: timedelta
        if asset_model.published_timestamp:
            timestamp: datetime = asset_model.published_timestamp
        else:
            timestamp: datetime = asset_model.created_timestamp

        # Make sure timestamp is timezone-aware
        if (timestamp.tzinfo is None
                or timestamp.tzinfo.utcoffset(timestamp) is None):
            timestamp = timestamp.replace(tzinfo=UTC)

        created_since = datetime.now(tz=UTC) - timestamp

        log_data['created_since'] = created_since
        if created_since < AssetCache.RECENT_THRESHOLD:
            _LOGGER.info('Adding asset to recent_uploads', extra=log_data)
            lists_set.add(AssetCache.DEFAULT_ASSET_LIST + short_append)

        metrics: dict[str, Counter | Gauge] = config.metrics
        metric = 'assetcache_lists_per_asset'
        if metrics and metric in metrics:
            metrics[metric].set(len(lists_set))

        return lists_set

    def metrics_setup(self) -> None:
        metrics: dict[str, Gauge | Counter] = config.metrics
        metric: str = 'assetcache_total_lists'
        if metrics and metric in metrics:
            return

        metrics[metric] = Gauge(
            metric, 'total lists in assetcache',
        )

        metric = 'assetcache_lists_per_asset'
        metrics[metric] = Gauge(
            metric, 'lists per asset in assetcache',
        )

        metric = 'assetcache_short_assets_added'
        metrics[metric] = Counter(
            metric, 'short assets (<60s) added to assetcache'
        )

        metric = 'assetcache_long_assets_added'
        metrics[metric] = Counter(
            metric, 'long assets (>60s) added to assetcache'
        )

        metric = 'assetcache_asset_found'
        metrics[metric] = Counter(
            metric, 'assets found in assetcache'
        )

        metric = 'assetcache_asset_not_found'
        metrics[metric] = Counter(
            metric, 'assets not found in assetcache'
        )

        metric = 'assetcache_refresh_asset_failures'
        metrics[metric] = Counter(
            metric,
            'Failures to call REST API of pod to refresh an asset'
        )

        metric = 'assetcache_refresh_asset_api_calls'
        metrics[metric] = Counter(
            metric, 'API calls to pods to refresh an asset'
        )

        metric = 'assetcache_refreshable_asset_not_found'
        metrics[metric] = Counter(
            metric, 'Assets not found in pods when refreshing'
        )

        metric = 'assetcache_refreshable_asset_dupes'
        metrics[metric] = Counter(
            metric, 'Multiple assets found in pod when refreshing'
        )
