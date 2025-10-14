'''
The searchable cache is based on Redis and supports lists of assets
and searching those assets. The searchable cache is used for the
assets the updates_worker and refresh_worker learn from the pods.

Lists can be things like 'recommended', 'recommended-vertical',
'sports-chess', 'music-rock-indie', etc.

With Redis, you create indexes based on a key prefix. All documents
with a key that starts with this prefix will be included in the
search. In this module we use the prefix '<list_name>:' so all assets
are stored in keys starting with that prefix.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from uuid import UUID
from typing import Self
from hashlib import sha256
from base64 import b64encode
from logging import Logger
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

import orjson

from redis import Redis
from redis.commands.core import Script

import redis.asyncio as redis

from redis.exceptions import ResponseError
from redis.commands.search.indexDefinition import IndexType
from redis.commands.search.indexDefinition import IndexDefinition

from redis.commands.search.query import Query
from redis.commands.search.field import Field
from redis.commands.search.result import Result
from redis.commands.search.field import TagField
from redis.commands.search.field import TextField
from redis.commands.search.field import NumericField

from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.datatypes import IngestStatus
from byoda.models.data_api_models import DEFAULT_PAGE_LENGTH

from byoda import config

from .asset_list import AssetList

_LOGGER: Logger = getLogger(__name__)

LUA_FUNCTION_NAME_GET_LIST_ASSETS: str = 'get_list_assets'


class SearchableCache:
    LUA_FUNCTIONS_FILE: str = 'byotubesvr/redis.lua'
    # Search index will index JSON values under this key prefix
    ASSET_KEY_PREFIX: str = 'assets:'
    ALL_ASSETS_LIST: str = 'all_assets'
    ALL_CREATORS: str = 'all_creators'
    CHANNEL_KEY_PREFIX: str = 'channels'

    DEFAULT_EXPIRATION: int = 86400             # seconds
    DEFAULT_EXPIRATION_LISTS: int = 90 * 86400  # days

    '''
    Data is arranged in Redis:
    - individual assets as JSON docs under 'assets:<cursor>'
    - lists of assets as a list of keys under:
      - 'lists:<list_name>'
      - 'sset:<list_name>

    The values of the elements of a list point to 'assets:<cursor>'
    The cursor is a base64-encoding of the SHA256 has of
    '<member_id>-<asset_id>'

    We maintain both sorted sets and lists in Redis as we need the
    list to enable pagination

    We use the sorted set both for checking whether an asset is already
    in a list and to get items from the set based on which ones are
    first to expire from the cache (using the Lua function).
    '''

    def __init__(self, connection_string: str) -> None:
        '''
        Constructor for the cache. Do not call directly but call .setup()
        as the LUA functions must be loaded first and the search index
        needs to be created

        :param connection_string: connection string for the Redis server
        '''

        self.client: Redis[any] = redis.from_url(
            connection_string, decode_responses=True
        )

        # The FT.SEARCH index
        self.index_name: str = \
            SearchableCache.ASSET_KEY_PREFIX.rstrip(':') + '_index'

        # This is the LUA function to get the values of assets in a list
        self._function_get_list_assets: Script | None = None

        self.setup_metrics()

    def setup_metrics(self) -> None:
        metrics: dict[str, Counter | Gauge] = config.metrics

        metric: str = 'searchable_cache_search_results_found'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'the number of search results found'
                )
            )

        metric: str = 'searchable_cache_asset_already_in_cache'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'The asset is already in the cache'
                )
            )

        metric: str = 'searchable_cache_asset_not_yet_in_cache'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'The asset is not yet in the cache and will be added'
                )
            )

    @staticmethod
    async def setup(connection_string: str,
                    lua_functions_file: str = LUA_FUNCTIONS_FILE) -> Self:
        '''
        Factory for SearchableCache, sets up the index and installs the LUA
        functions in the Redis server
        '''

        self = SearchableCache(connection_string)

        await self.create_search_index()
        await self.load_functions(lua_functions_file)

        return self

    async def create_search_index(self) -> None:
        try:
            await self.client.ft(self.index_name).info()
            _LOGGER.debug('Found existing search index so no action needed')
        except ResponseError as exc:
            if 'Unknown index name' not in str(exc):
                raise

            await self.create_index(SearchableCache.ASSET_KEY_PREFIX)
            _LOGGER.debug('Created search index')

    async def load_functions(self, lua_functions_file: str) -> None:
        try:
            with open(lua_functions_file) as file_desc:
                lua_code: str = file_desc.read()

            _LOGGER.debug(
                f'Loading Redis LUA function from {lua_functions_file}'
            )
            self._function_get_list_assets: Script = \
                self.client.register_script(lua_code)
            _LOGGER.debug('Loaded Redis LUA function')

        except ResponseError as exc:
            if not (str(exc).startswith('Library')
                    and str(exc).endswith('already exists')):
                _LOGGER.exception(f'Loading LUA function failed: {exc}')
                raise

        await self.client.ping()

    async def close(self) -> None:
        '''
        Closes the connection to the Redis server
        '''

        await self.client.aclose()

    @staticmethod
    def get_all_creators_key() -> str:
        return (
            f'{SearchableCache.CHANNEL_KEY_PREFIX}:'
            f'{SearchableCache.ALL_CREATORS}'
        )

    def get_cursor(self, member_id: str | UUID, asset_id: str | UUID) -> str:
        '''
        Calculates the cursor based on the combination of the member_id
        and asset_id

        :param member_id: The member_id that published the asset
        :param item_id: The item_id of the item, ie. asset_id or channel_id
        :param item_type: The type of the item
        :returns: The cursor as 12 character string consisting of characters
        matching the regex [a-zA-Z0-9\\@\\-]
        '''
        if isinstance(member_id, UUID):
            member_id = str(member_id)

        if isinstance(asset_id, UUID):
            asset_id = str(asset_id)

        hash_val: str = sha256(
            f'{member_id}-{asset_id}'.encode('utf-8'), usedforsecurity=False
        ).digest()

        cursor: str = b64encode(
            hash_val, '@-'.encode('utf-8')
        ).decode('utf-8')[0:12]

        return cursor

    def annotate_key(self, key_prefix: str, cursor: str) -> str:
        '''
        Annotates the key with the cursor for storage in the cache
        while conforming to the key prefix used for the search index
        '''

        return f'{key_prefix.rstrip(":")}:{cursor}'

    async def create_index(self, key_prefix: str) -> None:
        '''
        Creates a Full Text index for assets as defined in the service
        schema for 'byotube'

        :param key_prefix: The key prefix to use for the index
        '''
        schema: tuple[Field] = (
            TagField('$.cursor', as_name='cursor'),
            TextField('$.node.title', as_name='title', weight=4.0),
            TextField('$.node.subject', as_name='subject', weight=2.0),
            TextField('$.node.contents', as_name='contents', weight=1.0),
            TextField('$.node.creator', as_name='creator', weight=5.0),
            TextField('$.node.keywords', as_name='keywords', weight=3.0),
            TextField('$.node.annotations', as_name='annotations', weight=3.0),
            TextField('$.node.categories', as_name='categories', weight=3.0),
            TagField('$.node.ingest_status', as_name='ingest_status'),
            TagField('$.node.asset_id', as_name='asset_id'),
            TagField('$.node.locale', as_name='locale'),
            NumericField(
                '$.node.created_timestamp', as_name='created_timestamp',
                sortable=True
            ),
            NumericField(
                '$.node.published_timestamp', as_name='published_timestamp',
                sortable=True
            ),
        )

        key_prefix = key_prefix.rstrip(':') + ':'
        definition: IndexDefinition = IndexDefinition(
            prefix=[key_prefix], index_type=IndexType.JSON, language='English'
        )

        result: bytes = await self.client.ft(
            self.index_name
        ).create_index(schema, definition=definition)
        if result and result != 'OK':
            raise RuntimeError('Failed to create search index')

        _LOGGER.debug(f'Created search index: {self.index_name}')

        return None

    async def search(self, query: str, offset: int = 0, num: int = 10
                     ) -> list[dict[str, str | dict[str, any]]]:
        '''
        Perform a search in the cache

        :param query: The query to perform
        :param offset: The index of the first search result to return
        :param num: The maximum number of search results to return
        :returns: a list of assets matching the query
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        if offset < 0:
            offset = 0
        if offset > 1000:
            offset = 0

        if num < 0:
            num = 10
        if num > 100:
            num = 10

        _LOGGER.debug(f'Received search query: {query}')

        query = Query(query).paging(offset, num).timeout(5 * 1000)
        results: Result = await self.client.ft(self.index_name).search(query)

        # The data structure returned depends on the version of the response
        # protocol of the Redis APIs: v2 vs v3, which is configured in
        # config.yml
        result_data: dict[str, any]
        if isinstance(results, dict):
            # Redis response protocol v3
            result_data = results.get('results')
        elif hasattr(results, 'docs'):
            # Redis response protocol v2
            result_data = results.docs
        else:
            raise RuntimeError(
                'Could not locate search results in data structure'
            )

        data: list[dict[str, any]] = []
        doc_data: dict[str, dict[str, any]]
        for doc in result_data:
            if isinstance(doc, dict):
                # Redis response protocol v3
                if ('extra_attributes' not in doc
                        or '$' not in doc['extra_attributes']):
                    continue
                doc_data = orjson.loads(doc['extra_attributes']['$'])
            else:
                # Redis response protocol v2
                doc_data = orjson.loads(doc.json)

            if (doc_data['node']['ingest_status'] in (
                    IngestStatus.PUBLISHED.value,
                    IngestStatus.EXTERNAL.value)):
                data.append(doc_data)

        metrics['searchable_cache_search_results_found'].set(len(data))
        _LOGGER.debug(
            'Found assets for query',
            extra={'query': query, 'items': len(data)}
        )

        return data

    async def get_list_values(self, asset_list: str | AssetList,
                              key_prefix: str,
                              first: int = DEFAULT_PAGE_LENGTH,
                              after: str = None,
                              filter_name: str | None = None,
                              filter_value: any = None) -> list:
        '''
        Gets the values of the requested assets in a list

        :param asset_list: The name of the list of assets, including the list
        prefix
        :param first: The maximum number of assets to return
        :param after: The cursor to start after
        :returns: A list of assets
        '''

        if first is not None and (not isinstance(first, int) or first <= 0):
            raise ValueError('first must be a integer > 0')

        if isinstance(asset_list, str):
            asset_list = AssetList(asset_list, redis=self.client)

        if not after:
            after = ''

        if filter_value:
            filter_value = str(filter_value)

        log_data: dict[str, any] = {
            'asset_list': asset_list.name,
            'redis_key': asset_list.redis_key,
            'key_prefix': key_prefix,
            'first': first,
            'after': after,
            'filter_name': filter_name,
            'filter_value': filter_value
        }

        _LOGGER.debug('Getting list values', extra=log_data)

        data: list[bytes] = await self._function_get_list_assets(
            keys=[asset_list.redis_key], args=[
                key_prefix, first, after or '', filter_name or '',
                filter_value or ''
            ]
        )
        results: list = []
        for item in data:
            if item:
                results.append(orjson.loads(item))

        # Ordered set has ascending values while we want newest asset first
        results.reverse()

        log_data['assets_retrieved'] = len(results)

        _LOGGER.debug('Retrieved assets for list', extra=log_data)

        return results

    async def json_get(self, key_prefix: str, member_id: UUID | None = None,
                       asset_id: UUID | None = None) -> object:
        '''
        Gets a JSON value from the cache

        :param key_prefix: The key prefix to use for the index.
        :param member_id: if not set, the key prefix is assumed to be the
        actual key for the cache item
        :param asset_id: if not set, the key prefix is assumed to be the
        actual key for the cache item
        '''

        if bool(member_id) != bool(asset_id):
            raise ValueError('member_id and asset_id must be both set or not')

        key: str
        if member_id and asset_id:
            cursor: str = self.get_cursor(member_id, asset_id)
            key = self.annotate_key(key_prefix, cursor)
        else:
            key = key_prefix

        cached_data: any = await self.client.json().get(key)

        return cached_data

    async def json_set(self, asset_lists: set[AssetList],
                       asset_key_prefix: str, asset_edge: dict,
                       expires_in: int | float = DEFAULT_EXPIRATION) -> int:
        '''
        Adds a JSON document to the cache and adds it to the lists of assets

        :param asset_lists: The lists that the asset should be added to
        :param asset_key_prefix: The prefix for the key to store the asset
        :param member_id: The member that originated the asset
        :param asset_edge: The asset to add
        :param expires_in: number of seconds until the asset expires
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        log_data: dict[str, any] = {
            'asset_key_prefix': asset_key_prefix,
        }
        node: dict | None = asset_edge.get('node')
        if not node:
            raise ValueError('asset_edge does not contain a node')

        asset_id: UUID | str | None = node.get('asset_id')
        if not asset_id:
            raise ValueError('node does not contain an asset_id field')

        if not isinstance(asset_id, str):
            asset_id = str(asset_id)

        log_data['asset_id'] = asset_id

        member_id: UUID | str | None = asset_edge.get('origin')
        if not member_id:
            raise ValueError('node does not contain an origin field')

        if not isinstance(member_id, str):
            member_id = str(member_id)

        log_data['member_id'] = member_id

        creator: str = asset_edge['node']['creator']
        if not creator:
            raise ValueError(
                f'Asset {asset_id} from member {member_id} does not have '
                'a value for creator'
            )

        log_data['creator'] = creator

        log_data['asset_lists'] = [
            asset_list.name for asset_list in asset_lists
        ]

        asset_edge['cursor'] = self.get_cursor(member_id, asset_id)

        key: str = self.annotate_key(asset_key_prefix, asset_edge['cursor'])
        log_data['cache_key'] = key

        if await self.client.json().get(key):
            metrics['searchable_cache_asset_already_in_cache'].inc()
            _LOGGER.debug(
                'Asset is already in the cache, so updating the expiration of '
                'the existing cache entry', extra=log_data
            )
            await self.set_expiration(key, expires_in)

            if creator:
                await self.update_creator_list_expiration(creator, asset_lists)

            return expires_in

        metrics['searchable_cache_asset_not_yet_in_cache'].inc()
        result: bool = await self.client.json().set(key, '.', asset_edge)
        await self.set_expiration(key, expires_in)
        _LOGGER.debug('Added asset to cache', extra=log_data)

        if not result:
            raise RuntimeError('Failed to set JSON key')

        asset_list: AssetList
        for asset_list in asset_lists:
            _LOGGER.debug(
                'Adding key to list',
                extra=log_data | {
                    'key': key,
                    'list': asset_list.name,
                    'expires': node['published_timestamp']
                }
            )

            add_asset: bool = False
            is_channel_list: bool = asset_list.is_channel_list()
            if is_channel_list:
                add_asset = True
            else:
                length: int = await asset_list.length()
                if length < AssetList.IN_HEAD_LIST_LEN:
                    add_asset = True
                else:
                    in_head: bool = await asset_list.in_head(creator)
                    if not in_head:
                        add_asset = True

            if add_asset:
                await asset_list.add(
                    key, node['published_timestamp']
                )

        # For the ALL_ASSETS_LIST, we use cache expiration to rank
        # entries in the Redis sorted-set. For all other lists we use
        # the publication timestamp
        asset_list = AssetList(
            SearchableCache.ALL_ASSETS_LIST, redis=self.client
        )
        await self.add_to_list(
            asset_list, key,
            datetime.now(tz=UTC) + timedelta(seconds=expires_in)
        )

    async def update_creator_list_expiration(
        self, creator: str, asset_lists: set[AssetList]
    ) -> None:
        for asset_list in [
            a_l for a_l in asset_lists if a_l.name.endswith(creator)
        ]:
            asset_sset_key: str
            asset_sset_key = AssetList.get_key(asset_list)
            await self.set_expiration(
                asset_sset_key, self.DEFAULT_EXPIRATION_LISTS
            )

    async def get_oldest_expired_item(self, stale_window: int = 0
                                      ) -> tuple[str, float] | None:
        '''
        Gets the oldest item in a list

        :param stale_window: The time before the asset expiration where we
        consider the asset stale
        :returns: The key for the oldest expired item in the ALL_ASSETS_LIST
        list and a timestamp for its expiration or none if the list is empty
        or the oldest item has not expired yet
        '''

        sset_key: str
        sset_key: str = AssetList.get_key(SearchableCache.ALL_ASSETS_LIST)
        items: list[tuple[str, float]] = await self.client.zpopmin(sset_key)

        if not items:
            return None

        sset_item: str = items[0][0]
        item_expires_at: float = items[0][1]
        # Suppose item expiration at 16:00
        # Suppose now is 15:00
        # Suppose stale window is 2 hours
        # so, now + stale window > item expiration
        if item_expires_at > datetime.now(tz=UTC).timestamp() + stale_window:
            # Oldest item has not expired and is not stale yet
            # Add the item back to the sorted set
            await self.client.zadd(sset_key, {sset_item: item_expires_at})
            return None, None

        return items[0]

    async def add_to_list(self, asset_list: AssetList, item: str,
                          timestamp: datetime | int | float | None,
                          to_back: bool = False
                          ) -> int:
        '''
        Adds an item to the list

        :param list: The name of the list
        :param item: The item to add
        :param timestamp: when the asset was published, or when the
        asset expires from the cache. Used for ranking the item in the sorted
        set
        :returns: The length of the list after adding the item
        '''

        if isinstance(timestamp, datetime):
            timestamp = timestamp.timestamp()

        do_insert = False
        list_len: int = await asset_list.length()

        if list_len < AssetList.IN_HEAD_LIST_LEN:
            do_insert = True

        if not await asset_list.contains_cursor(item):
            do_insert = True

        if do_insert:
            await asset_list.add(item, timestamp, to_back=to_back)
            list_len += 1

        await asset_list.set_expiration()

        return list_len

    async def get_expiration(self, key: str) -> int:
        '''
        Get the expiration for a key in the cache

        :param key: the key to set the expiration for
        :returns: the number of seconds until the key expires
        '''

        return await self.client.ttl(key)

    async def set_expiration(self, key: str,
                             expires_in: int | float = DEFAULT_EXPIRATION
                             ) -> int:
        '''
        Sets the expiration for a key in the cache

        :param key: the key to set the expiration for
        :param expires: the number of seconds until the key expires
        '''

        return await self.client.expire(key, int(expires_in))
