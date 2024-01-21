'''
Asset Cache maintains lists of assets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

from uuid import UUID
from typing import Self
from typing import TypeVar
from logging import getLogger
from datetime import datetime

from fastapi.encoders import jsonable_encoder

from byoda.datatypes import DataRequestType

from byoda.models.data_api_models import EdgeResponse as Edge
from byoda.models.data_api_models import Asset

# from byoda.secrets.service_secret import ServiceSecret

from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.service_secret import ServiceSecret

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda.datacache.searchable_cache import SearchableCache

_LOGGER: Logger = getLogger(__name__)


Member = TypeVar('Member')

AssetType = TypeVar('AssetType')


class AssetCache(SearchableCache):
    ASSET_KEY_PREFIX: str = 'assets:'
    DEFAULT_ASSET_LIST: str = 'recent_uploads'
    DEFAULT_ASSET_EXPIRATION: int = 60 * 60 * 24 * 3  # 3 days
    # The worker stores here all the lists that have been generated
    # based on the assets it has collected.
    LIST_OF_LISTS_KEY: str = 'list_of_lists'
    # This list used to refresh assets in the cache. The list is
    # ordered from newest to oldest asset in the cache
    ALL_ASSETS_LIST: str = 'all_assets'

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
    async def setup(connection_string: str) -> Self:
        '''
        Setup the cache and return an instance.

        :param connection_string: The connection string to the Redis server.
        :return: An instance of the AssetCache class.
        :raises: None
        '''

        self: AssetCache = AssetCache(connection_string)
        await self.create_search_index()
        await self.load_functions()

        return self

    async def pos(self, list_name: str, cursor: str) -> int:
        '''
        Gets the position of an item in the list

        :param cursor: the cursor of the item to find
        :returns: the position of the item in the list
        '''

        key: str = self.json_key(list_name)

        return await self.backend.pos(key, cursor)

    async def add_asset(self, member_id, asset: dict) -> None:
        '''
        Add an asset to the cache.

        :param member_id: The member that originated the asset.
        :param asset: The asset to add.
        :return: None
        :raises: None
        '''

        pydantic_asset: Asset = Asset(**asset)

        # We use short_append to make sure vertically oriented assets
        # go to separate lists from horizontally oriented assets.
        short_append: str = ''
        if pydantic_asset.duration <= 60:
            pydantic_asset.screen_orientation_horizontal = False
            short_append = '-short'

        # the 'all_assets' list is a special list that contains all assets, so
        # we can refresh assets in the cache before they expire
        lists_set: set[str] = set(
            [
                AssetCache.DEFAULT_ASSET_LIST + short_append,
                AssetCache.ALL_ASSETS_LIST
            ]
        )

        categories: list[str] | None = pydantic_asset.categories
        if len(categories) > 2:
            categories = categories[:2]

        keywords: list[str] = pydantic_asset.keywords
        if len(keywords) > 4:
            keywords = keywords[:4]

        annotations: list[str] = pydantic_asset.annotations
        if len(annotations) > 4:
            annotations = annotations[:4]

        # Create the lists that we will add the asset to.
        # Structure is: <category>-<keyword>-<annotation>-<short>
        category: str
        keyword: str
        annotation: str
        for category in pydantic_asset.categories:
            list_name: str = category + short_append
            lists_set.add(list_name)
            for keyword in pydantic_asset.keywords:
                list_name: str = category + '-' + keyword + short_append
                lists_set.add(list_name)
                for annotation in pydantic_asset.annotations:
                    list_name = (
                        category + '-' + keyword + '-' + annotation +
                        short_append
                    )
                    lists_set.add(list_name)

        # We don't want too many lists
        if len(lists_set) > 32:
            lists_set = set((list(lists_set))[:32])

        lists_set.add(pydantic_asset.creator + short_append)

        # We override the cursor that the member may have set as that cursor
        # is only unique(-ish) for the member. We need a cursor that is unique
        # globally.
        server_cursor: str = self.get_cursor(
            member_id, pydantic_asset.asset_id
        )

        asset_edge: Edge[Asset] = Edge[Asset](
            node=pydantic_asset,
            origin=member_id,
            cursor=server_cursor
        )

        # We replace UUIDs with strings and datetimes with timestamps. The
        # get_asset() method will case to Pydantic model and that will return
        # the values to their proper type
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

        await self.update_list_of_lists(lists_set)

        _LOGGER.debug(
            f'Added asset {pydantic_asset.asset_id} '
            f'to cache for {len(lists_set)} lists'
        )

    async def get_asset_by_key(self, asset_key: str) -> Edge:
        '''
        Get an asset by its key.

        :param asset_key: The key of the asset to get.
        :return: The asset.
        :raises: None
        '''

        asset_data: any = await self.json_get(asset_key)
        if not asset_data:
            raise FileNotFoundError(f'Asset not found for key: {asset_key}')

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

    async def get_list_assets(self,
                              asset_list: str = DEFAULT_ASSET_LIST,
                              first: int = 20, after: str | None = None
                              ) -> list[Edge]:
        '''
        Get a page worth of assets from a list
        '''

        data: list[dict] = await self.get_list_values(
            asset_list, AssetCache.ASSET_KEY_PREFIX, first=first, after=after
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

        list_name: str = AssetCache.ALL_ASSETS_LIST
        asset_key: str | None = await self.pop_last_list_item(list_name)
        if not asset_key:
            return None

        edge: Edge = await self.get_asset_by_key(asset_key)
        return edge

    async def push_newest_asset(self, edge: Edge) -> int:
        '''
        Pushes the newest asset to the top of the list

        :returns: The length of the list after adding the item
        '''

        cursor: str = self.get_cursor(edge.origin, edge.node.asset_id)
        asset_key: str = AssetCache.ASSET_KEY_PREFIX + cursor

        list_name: str = AssetCache.ALL_ASSETS_LIST

        return await self.prepend_list(list_name, asset_key)

    async def update_list_of_lists(self, lists: set[str]) -> None:
        '''
        Update the list of lists.

        :param lists: The lists to add to the list of lists.
        :return: None
        :raises: None
        '''

        await self.client.sadd(AssetCache.LIST_OF_LISTS_KEY, *lists)

    async def get_list_of_lists(self) -> set[str] | None:
        '''
        Get the list of lists.

        :return: The list of lists.
        :raises: None
        '''

        lists: set[bytes] = await self.client.smembers(
            AssetCache.LIST_OF_LISTS_KEY
        )
        return lists

    async def exists_list(self, list_name: str) -> bool:
        '''
        Check if a list exists.

        :param list_name: The name of the list to check.
        :return: True if the list exists, False otherwise.
        :raises: None
        '''

        return await self.client.exists(self.get_list_key(list_name))

    async def delete_list(self, list_name: str) -> None:
        '''
        Delete a list.

        :param list_name: The name of the list to delete.
        :return: None
        :raises: None
        '''

        return bool(await self.client.delete(self.get_list_key(list_name)))

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

        key: str = AssetCache.get_asset_key(member_id, asset_id)

        return await self.backend.delete(key)

    async def refresh_asset(self, edge: Edge, asset_class_name: str,
                            tls_secret: MemberSecret | ServiceSecret
                            ) -> Edge:
        '''
        Renews an asset in the cache

        :param member_id: the member_id of the member that owns the asset
        :param asset_id: the asset_id of the asset to renew
        :param tls_secret: the TLS secret to use when calling members
        to see if the asset still exists
        :returns: the renewed asset
        '''

        member_id: UUID = edge.origin
        node: Asset = edge.node
        asset_id: UUID = node.asset_id

        resp: HttpResponse = await self._asset_query(
            member_id, asset_id, asset_class_name, tls_secret
        )

        if resp.status_code != 200:
            raise FileNotFoundError

        data = resp.json()

        if not data or data.get('total_count') == 0:
            raise FileNotFoundError

        if data['total_count'] > 1:
            _LOGGER.debug(
                f'Multiple assets found for asset_id {asset_id} '
                f'from member {member_id}, using only the first one'
            )

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

        data_filter: dict[str, dict[str, object]] | None = None
        if asset_id:
            data_filter: dict = {'asset_id': {'eq': asset_id}}

        resp: HttpResponse = await DataApiClient.call(
            tls_secret.service_id, asset_class_name,
            action=DataRequestType.QUERY, secret=tls_secret,
            network=tls_secret.network, member_id=member_id,
            data_filter=data_filter, first=1,
        )

        return resp
