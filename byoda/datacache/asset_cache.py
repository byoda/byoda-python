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
    RECENT_THRESHOLD: timedelta = timedelta(days=2)

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

    async def pos(self, list_name: str, cursor: str) -> int:
        '''
        Gets the position of an item in the list

        :param cursor: the cursor of the item to find
        :returns: the position of the item in the list
        '''

        key: str = self.json_key(list_name)

        return await self.backend.pos(key, cursor)

    async def add_newest_asset(self, member_id: UUID, asset: dict) -> bool:
        '''
        Add an asset to the cache.

        :param member_id: The member that originated the asset.
        :param asset: The asset to add.
        :return: None
        :raises: None
        '''

        metrics: dict[str, Gauge | Counter] = config.metrics

        asset_model: Asset = Asset(**asset)

        # The various lists that this asset should be added to
        lists_set: set[str] = AssetCache.get_list_permutations(
            member_id, asset_model
        )

        # We override the cursor that the member may have set as that cursor
        # is only unique(-ish) for the member. We need a cursor that is unique
        # globally.
        server_cursor: str = self.get_cursor(member_id, asset_model.asset_id)

        asset_edge: Edge[Asset] = Edge[Asset](
            node=asset_model,
            origin=member_id,
            cursor=server_cursor
        )

        if not asset_model.creator:
            _LOGGER.debug(
                f'Not adding asset {asset_model.asset_id} '
                f'from member {member_id} with no creater'
            )
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
            lists_set, AssetCache.ASSET_KEY_PREFIX, asset_data
        )

        await self.update_creators_list(member_id, asset_model.creator)

        await self.update_list_of_lists(lists_set)
        metric: str = 'assetcache_total_lists'
        if metrics and metric in metrics:
            metrics[metric].set(len(lists_set))

        _LOGGER.debug(
            f'Added asset {asset_model.asset_id} '
            f'to cache for {len(lists_set)} lists'
        )

        return True

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

    async def get_asset_expiration(self, node: str | Edge) -> int:
        '''
        Gets the expiration time of an asset

        :param node: either the cursor of the asset to get the expiration time
        for or the edge of the asset to get the expiration time for
        :returns: the expiration time of the asset
        '''

        if isinstance(node, Edge):
            cursor: str = self.get_cursor(node.origin, node.node.asset_id)
        else:
            cursor = node

        asset_key: str = AssetCache.ASSET_KEY_PREFIX + cursor

        _LOGGER.debug('Getting asset expiration for asset key: ' + asset_key)

        return await self.get_expiration(asset_key)

    async def add_oldest_asset(self, node: str | Edge) -> None:
        '''
        Adds the cursor for the oldest asset back to the front of the list

        :param node: push the asset back to the start of the all_assets list
        :returns: the length of the list after adding the item
        '''

        if isinstance(node, Edge):
            cursor: str = self.get_cursor(node.origin, node.node.asset_id)
        else:
            cursor = node

        asset_key: str = AssetCache.ASSET_KEY_PREFIX + cursor

        list_name: str = AssetCache.ALL_ASSETS_LIST

        return await self.append_list(list_name, asset_key)

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

    async def get_oldest_asset(self) -> Edge | None:
        '''
        Get the oldest asset in the cache, that needs to
        be refreshed first

        :returns: the cache key for the oldest asset in the cache
        '''

        asset_key: str | None = await self.pop_last_list_item(
            AssetCache.ALL_ASSETS_LIST
        )
        if not asset_key:
            return None

        edge: Edge = await self.get_asset_by_key(asset_key)
        return edge

    async def update_creators_list(self, member_id: UUID, creator: str
                                   ) -> None:
        '''
        Updates:
        - the expiration for the list of all assets of the creator (without
        member_id embedded in the key, which is a BUG)
        - the set of all creators
        - the list of all creators

        :param creator: The creator to add to the list of creators.
        :return: None
        :raises: None
        '''

        if not creator:
            _LOGGER.debug('No creator to add to the list of creators')

        creator_list: str = self.get_list_key(creator)
        await self.set_expiration(creator_list)

        cursor: str = ChannelCache.get_cursor(member_id, creator)

        set_key: str = self.get_set_key(ChannelCache.ALL_CREATORS)
        _LOGGER.debug(
            f'Reviewing list of creators with key {set_key} '
            f'for cursor {cursor}'
        )
        if await self.client.sismember(set_key, cursor):
            _LOGGER.debug(
                f'Creator {creator} with cursor {cursor} already in the set '
                f'of all creators with key {set_key}'
            )
            await self.set_expiration(
                set_key, AssetCache.DEFAULT_EXPIRATION_LISTS
            )
            return

        _LOGGER.debug(
            f'Adding creator {creator} to the set of all creators '
            f'with cursor {cursor}'
        )
        await self.client.sadd(set_key, cursor)
        await self.set_expiration(
            set_key, AssetCache.DEFAULT_EXPIRATION_LISTS
        )

        list_key: str = self.get_list_key(ChannelCache.ALL_CREATORS)
        _LOGGER.debug(
            f'Adding creator {creator} to the list {list_key} '
            f'with cursor {cursor}'
        )
        await self.client.lpush(list_key, cursor)

        await self.set_expiration(
            list_key, ChannelCache.DEFAULT_EXPIRATION_LISTS
        )

    async def get_creators_list(self) -> set[str] | None:
        '''
        Get the list of creators.

        :return: The list of creators.
        :raises: None
        '''

        key: str = self.get_set_key(AssetCache.ALL_CREATORS)
        creators: set[bytes] = await self.client.smembers(key)

        _LOGGER.debug(f'Found {len(creators)} for set with key {key}')
        return creators

    async def update_list_of_lists(self, lists: set[str]) -> None:
        '''
        Update the list of lists.

        :param lists: The lists to add to the list of lists.
        :return: None
        :raises: None
        '''

        key: str = self.get_list_key(AssetCache.LIST_OF_LISTS_KEY)
        await self.client.sadd(key, *lists)

    async def get_list_of_lists(self) -> set[str] | None:
        '''
        Get the list of lists.

        :return: The list of lists.
        :raises: None
        '''

        key: str = self.get_list_key(AssetCache.LIST_OF_LISTS_KEY)
        lists: set[bytes] = await self.client.smembers(key)
        return lists

    async def exists_list(self, list_name: str) -> bool:
        '''
        Check if a list exists.

        :param list_name: The name of the list to check.
        :return: True if the list exists, False otherwise.
        :raises: None
        '''

        key: str = self.get_list_key(list_name)
        return await self.client.exists(key)

    async def delete_list(self, list_name: str) -> None:
        '''
        Delete a list.

        :param list_name: The name of the list to delete.
        :return: None
        :raises: None
        '''

        key: str = self.get_list_key(list_name)
        return bool(await self.client.delete(key))

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

        try:
            resp: HttpResponse = await self._asset_query(
                member_id, asset_id, asset_class_name, tls_secret
            )
        except Exception as exc:
            _LOGGER.debug(
                f'Error calling data API of member {member_id}: {exc}'
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
                f'Multiple assets found for asset_id {asset_id} '
                f'from member {member_id}, using only the first one'
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

        resp: HttpResponse = await DataApiClient.call(
            tls_secret.service_id, asset_class_name,
            action=DataRequestType.QUERY, secret=tls_secret,
            network=tls_secret.network, member_id=member_id,
            data_filter=data_filter, first=1,
        )

        metric: str = 'assetcache_refresh_asset_api_calls'
        if metrics and metric in metrics:
            metrics[metric].inc()

        return resp

    @staticmethod
    def get_short_appendix(asset_model: Asset) -> str:
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

        # the 'all_assets' list is a special list that contains all assets, so
        # we can refresh assets in the cache before they expire
        lists_set.add(AssetCache.ALL_ASSETS_LIST)

        # Add the asset to the list for the creator
        if asset_model.creator:
            # TODO: we maintain two lists for the creator as the
            # /api/v1/service/data API does not yet include the member_id
            # in the list of assets to retrieve
            lists_set.add(asset_model.creator + short_append)
            lists_set.add(f'{member_id}_{asset_model.creator}{short_append}')
        else:
            _LOGGER.debug(
                f'No creator for asset {asset_model.asset_id} '
                'from member {asset_model.origin}'
            )

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

        if created_since < AssetCache.RECENT_THRESHOLD:
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
