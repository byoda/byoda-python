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
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from uuid import UUID
from typing import Self
from hashlib import sha256
from base64 import b64encode
from logging import getLogger
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

from byoda.util.logger import Logger

from byoda import config

_LOGGER: Logger = getLogger(__name__)

LUA_FUNCTION_NAME_GET_LIST_ASSETS: str = 'get_list_assets'


class SearchableCache:
    LUA_FUNCTIONS_FILE: str = 'byotubesvr/redis.lua'
    # Search index will index JSON values under this key prefix
    ASSET_KEY_PREFIX: str = 'assets:'
    LISTS_KEY_PREFIX: str = 'lists:'
    SETS_KEY_PREFIX: str = 'sets:'
    ALL_ASSETS_LIST: str = 'all_assets'
    ALL_CREATORS: str = 'all_creators'

    DEFAULT_EXPIRATION: int = 86400             # seconds
    DEFAULT_EXPIRATION_LISTS: int = 30 * 86400  # days

    '''
    Data is arranged in Redis:
    - individual assets as JSON docs under 'assets:<cursor>'
    - lists of assets as a list of keys under 'lists:<list_name>'
      the values of the elements of a list point to 'assets:<cursor>'

    The cursor is a base64-encoding of the SHA256 has of
    '<member_id>-<asset_id>'
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
        metrics: dict[str, Gauge | Counter] = config.metrics

        metric: str = 'searchable_cache_member_id_in_head_of_list'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'an origin of an asset already has another asset in the '
                    'head of the list'
                )
            )

        metric = 'searchable_cache_member_id_not_in_head_of_list'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'an origin of an asset already does not have another '
                    'asset in the head of the list'
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

    def get_list_key(self, cache_list: str, is_internal: bool = False,
                     member_id: UUID | None = None) -> str:
        '''
        Get the Redis key for the list of assets

        :param cache_list: The name of the list of assets
        :returns: The Redis key for the list of assets
        '''

        # BUG: the member_id option should not be optional
        # but the /api/v1/service/data API currently does not
        # require a member_id

        mid: str = ''
        if member_id:
            mid = f'{member_id}_'
        if is_internal:
            return f'_{self.LISTS_KEY_PREFIX}{mid}{cache_list}'
        else:
            return f'{self.LISTS_KEY_PREFIX}{mid}{cache_list}'

    def get_set_key(self, cache_set: str) -> str:
        '''
        Get the Redis key for the list

        :param cache_list: The name of the list of assets
        :returns: The Redis key for the list of assets
        '''

        return f'_{self.SETS_KEY_PREFIX}{cache_set}'

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

        _LOGGER.debug(f'Found {len(data)} assets for query: {query}')

        return data

    async def get_list_values(self, asset_list: str, key_prefix: str,
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

        asset_list_key: str = self.get_list_key(asset_list)

        if not after:
            after = ''

        if filter_value:
            filter_value = str(filter_value)

        data: list[bytes] = await self._function_get_list_assets(
            keys=[asset_list_key], args=[
                key_prefix, first, after or '', filter_name or '',
                filter_value or ''
            ]
        )
        results: list = []
        for item in data:
            if item:
                results.append(orjson.loads(item))

        log_message: str = \
            f'Got {len(results)} assets for key {asset_list_key} '

        if after:
            log_message += f'after {after}'
        if first:
            log_message += f' with first {first}'
        if filter_value:
            log_message += f' and filter {filter_name}={filter_value}'

        _LOGGER.debug(log_message)

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

    async def json_set(self, asset_lists: str | list[str] | set[str],
                       asset_key_prefix: str, asset_edge: dict,
                       expiration: int = DEFAULT_EXPIRATION) -> int:
        '''
        Adds a JSON document to the cache and adds it to the lists of assets

        :param asset_lists: The lists that the asset should be added to
        :param asset_key_prefix: The prefix for the key to store the asset
        :param member_id: The member that originated the asset
        :param asset_edge: The asset to add
        '''

        metrics: dict[str, Gauge | Counter] = config.metrics

        node: dict | None = asset_edge.get('node')
        if not node:
            raise ValueError('asset_edge does not contain a node')

        asset_id: UUID | str | None = node.get('asset_id')
        if not asset_id:
            raise ValueError('node does not contain an asset_id field')

        if not isinstance(asset_id, str):
            asset_id = str(asset_id)

        member_id: UUID | str | None = asset_edge.get('origin')
        if not member_id:
            raise ValueError('node does not contain an origin field')

        if not isinstance(member_id, str):
            member_id = str(member_id)

        creator: str = asset_edge['node']['creator']
        if not creator:
            raise ValueError(
                f'Asset {asset_id} from member {member_id} does not have '
                'a value for creator'
            )

        if type(asset_lists) not in (set, list):
            asset_lists = [asset_lists]

        asset_edge['cursor'] = self.get_cursor(member_id, asset_id)

        key: str = self.annotate_key(asset_key_prefix, asset_edge['cursor'])
        if await self.client.json().get(key):
            _LOGGER.debug(
                f'Asset {asset_edge["node"]["asset_id"]} is already '
                f'in the cache: {key}, so only updating the expiration'
            )
            await self.set_expiration(key, expiration)

            if creator:
                for asset_list in [
                    a_l for a_l in asset_lists if a_l.endswith(creator)
                ]:
                    # BUG: we currently maintain two lists: <prefix>:<creator>
                    # and <prefix>:<member_id>_{creator}
                    asset_list_key: str = self.get_list_key(asset_list)
                    await self.set_expiration(
                        asset_list_key, self.DEFAULT_EXPIRATION_LISTS
                    )
                    asset_list_key: str = self.get_list_key(
                        asset_list, member_id=member_id
                    )
                    await self.set_expiration(
                        asset_list_key, self.DEFAULT_EXPIRATION_LISTS
                    )

            return

        result: bool = await self.client.json().set(key, '.', asset_edge)

        if not result:
            raise RuntimeError('Failed to set JSON key')

        await self.set_expiration(key, expiration)

        for asset_list in asset_lists:
            if (asset_list != SearchableCache.ALL_ASSETS_LIST
                    and not asset_list.endswith(creator)):
                origin_already_in_head_of_list: bool = \
                    await self.check_head_of_list(
                        asset_list, creator, depth=20
                    )

                if origin_already_in_head_of_list:
                    metric: str = \
                        'searchable_cache_member_id_in_head_of_list'
                    metrics[metric].inc()
                    continue

            metric: str = \
                'searchable_cache_member_id_not_in_head_of_list'
            metrics[metric].inc()

            _LOGGER.debug(f'Prepending key {key} to list {asset_list}')
            await self.prepend_list(asset_list, key)

    async def check_head_of_list(self, list_name: str, creator: str,
                                 depth: int = 20) -> bool:
        '''
        Checks if an asset of the same origin is already in the first
        '<depth>' items of the list

        :param list_name: The name of the list
        :param member_id: The member that originated the asset
        :returns: True if an asset with the member_id = origin
        is already in the first <depth> items of the list
        '''

        key_name: str = self.get_list_key(list_name)
        asset_keys: list[str] = await self.client.lrange(key_name, 0, depth)
        _LOGGER.debug(f'Getting first {depth} items of list {list_name}')
        for asset_key in asset_keys:
            edge: dict[str, any] = await self.client.json().get(asset_key)
            if not edge:
                continue
            edge_creator: str = edge['node']['creator']
            _LOGGER.debug(
                f'Checking asset {asset_key} to see if it is '
                f'from creator {creator}: {edge_creator}'
            )
            if edge and edge['node']['creator'] == creator:
                _LOGGER.debug(
                    f'Creator {creator} with asset {asset_key} already '
                    f'in head of list {list_name}'
                )
                return True

        return False

    async def pop_last_list_item(self, list_name: str) -> str | None:
        '''
        Gets the last item in a list

        :param list: The name of the list
        :returns: The key for the last item in the list or none if the list is
        empty. The key includes the prefix and the cursor
        '''

        key_name: str = self.get_list_key(list_name)
        item: str = await self.client.rpop(key_name)

        return item

    async def push_newest_list_item(self, list_name: str, item: str) -> int:
        '''
        Adds an item to the end of a list

        :param list: The name of the list
        :param item: The item to add
        :returns: The length of the list after adding the item
        '''

        key_name: str = self.get_list_key(list_name)
        return await self.client.rpush(key_name, item)

    async def append_list(self, list_name: str, item: str) -> int:
        '''
        Adds an item to the end of a list

        :param list: The name of the list
        :param item: The item to add
        :returns: The length of the list after adding the item
        '''

        key_name: str = self.get_list_key(list_name)
        await self.client.expire(
            key_name, time=timedelta(seconds=self.DEFAULT_EXPIRATION_LISTS)
        )
        return await self.client.rpush(key_name, item)

    async def prepend_list(self, list_name: str, item: str,
                           is_internal: bool = False) -> int:
        '''
        Adds an item to the beginning of a list

        :param list: The name of the list
        :param item: The item to add
        :returns: The length of the list after adding the item
        '''

        key_name: str = self.get_list_key(list_name, is_internal=is_internal)
        await self.client.expire(
            key_name, time=timedelta(seconds=self.DEFAULT_EXPIRATION_LISTS)
        )
        return await self.client.lpush(key_name, item)

    async def get_expiration(self, key: str) -> int:
        '''
        Get the expiration for a key in the cache

        :param key: the key to set the expiration for
        :returns: the number of seconds until the key expires
        '''

        return await self.client.ttl(key)

    async def set_expiration(self, key: str, seconds: int = DEFAULT_EXPIRATION
                             ) -> int:
        '''
        Sets the expiration for a key in the cache

        :param key: the key to set the expiration for
        :param seconds: the number of seconds to set the expiration for
        '''

        return await self.client.expire(key, seconds)
