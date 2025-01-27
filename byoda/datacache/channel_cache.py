'''
Asset Cache maintains lists of channels

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import base64

from uuid import UUID
from typing import Self
from logging import getLogger, Logger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from redis import Redis

from fastapi.encoders import jsonable_encoder

from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.datamodel.metrics import Metrics

from byoda.models.data_api_models import Channel

from byoda.models.data_api_models import EdgeResponse as Edge

from byoda.datacache.searchable_cache import SearchableCache
from byoda.datacache.asset_list import AssetList

from byoda import config

_LOGGER: Logger = getLogger(__name__)


class ChannelCache(SearchableCache, Metrics):
    '''
    We cache the data about all channels/creators to show
    channel information in the UI

    channel/creator are used interchangeably but we should
    use creator as a person or organization and the creator can
    have one or more channels.

    The name of a channel is not unique, that's why we use
    member_id to differentiate between channels with the same name
    on different pods.
    '''
    CHANNEL_SHORTCUT_PREFIX: str = 'channel_shortcuts'
    CHANNEL_SHORTCUT_EXPIRATION: int = 2 * 365 * 24 * 60 * 60

    def __init__(self, connection_string: str) -> None:
        '''
        Constructor for the ChannelCache class

        :param connection_string: the connection string for the
        Read/Write-enabled cache
        '''

        super().__init__(connection_string)

        self.setup_metrics()

        self.channel_list: AssetList = AssetList(
            ChannelCache.ALL_CREATORS, False, self.client
        )

    @staticmethod
    async def setup(connection_string: str) -> Self:
        '''
        Factory for the ChannelCache class

        :param connection_string: the connection string for the cache
        :returns: instance of ChannelCache
        :raises: (none)
        '''

        self: ChannelCache = ChannelCache(connection_string)

        await self.create_search_index()

        return self

    @staticmethod
    def get_channel_key(member_id: UUID, creator: str,
                        is_internal_list: bool = False) -> str:
        '''
        Get the key for the channel

        :param channel_name: the name of the channel
        :param is_internal_list: whether the channel is an internal list
        :returns: the key for the channel
        '''

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        if not isinstance(creator, str):
            raise ValueError(f'Creator must be a string: {creator}')

        cursor: str = ChannelCache.get_cursor(member_id, creator)

        key: str = ChannelCache.get_channel_key_for_cursor(
            cursor, is_internal_list
        )

        return key

    @staticmethod
    def get_channel_key_for_cursor(cursor: str, is_internal_list: bool = False
                                   ) -> str:
        '''
        Get the key for the channel

        :param cursor: the cursor for the channel
        :returns: the key for the channel
        '''

        if not isinstance(cursor, str):
            raise ValueError(f'Cursor must be a string: {cursor}')

        key: str = f'{ChannelCache.CHANNEL_KEY_PREFIX}:{cursor}'

        if is_internal_list:
            key = f'_{key}'

        return key

    def get_asset_list(self, name: str, is_internal: bool, redis: Redis
                       ) -> AssetList:
        if name in self.list_cache:
            _LOGGER.debug('Found existing asset list', extra={'list': name})
            return self.list_cache[name]

        asset_list = AssetList(name, is_internal, redis)
        return asset_list

    async def add_newest_channel(self, member_id: UUID | str,
                                 channel: Channel | dict[str, any]) -> bool:
        '''
        Add a channel to the cache and to the list of all channels

        :param channel: the channel to add
        :returns: number of lists the channel was added to
        '''

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        if not isinstance(channel, Channel):
            channel = Channel(**channel)

        result: bool = await self.add_to_cache(member_id, channel)

        # Check if channel is already in list of channels/creators
        channel_key: str = ChannelCache.get_channel_key(
            member_id, channel.creator
        )

        all_creators_key: str = SearchableCache.get_all_creators_key()
        if await self.client.zscore(all_creators_key, channel_key):
            _LOGGER.debug('Channel already in list of channels')
            return result

        await self.append_channel(member_id, channel)

        return result

    async def append_channel(self, member_id: UUID, channel: Channel
                             ) -> bool:
        '''
        Add a channel to the end of the list of all channels. If the
        channel already exists then it is moved to the end of the list.

        :param channel: the channel to add
        :returns: number of lists the channel was added to
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        if not isinstance(channel, Channel):
            channel = Channel(**channel)

        all_creators_key: str = ChannelCache.get_all_creators_key()
        channel_key: str = ChannelCache.get_channel_key(
            member_id, channel.creator
        )
        log_extra: dict[str, str] = {
            member_id: member_id,
            'channel': channel.creator,
            'channel_key': channel_key,
            'all_creators_key': all_creators_key
        }
        now: float = datetime.now(tz=UTC).timestamp()
        await self.client.zadd(all_creators_key, {channel_key: now})
        await self.client.expire(
            all_creators_key, time=timedelta(
                seconds=self.DEFAULT_EXPIRATION_LISTS
            )
        )
        _LOGGER.debug('Added channel to all_creators list', extra=log_extra)
        metric: str = 'channelcache_total_channels'
        metrics[metric].inc()

    async def get_oldest_channel(self) -> Edge[Channel] | None:
        '''
        Removes and returns the oldest channel in the cache

        :returns: None if no channels are in the list, Edge[Channel] if a
        channel is in the list
        the oldest channel in the cache
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        all_creators_key: str = ChannelCache.get_all_creators_key()

        data: list[tuple[str, str]] | None = await self.client.zpopmin(
            all_creators_key, 1
        )
        if not data:
            _LOGGER.debug('No channels in the cache')
            return None

        metric: str = 'channelcache_total_channels'
        metrics[metric].dec()

        try:
            member_id: UUID
            creator: str
            key_name: str = data[0][0]
            member_id, creator = ChannelCache.parse_channel_key(key_name)
            _LOGGER.debug('Got oldest channel', {'creator': creator})
        except Exception as exc:
            _LOGGER.warning(f'Invalid channel data {data}: {exc}')
            return None

        # Create a channel edge with placeholder data
        channel: Channel = Channel(creator=creator)
        cursor: str = ChannelCache.get_cursor(member_id, creator)
        key: str = ChannelCache.get_channel_key(member_id, creator)
        edge = Edge(
            cursor=cursor, node=channel, origin=member_id, expires_at=0
        )

        log_extra: dict[str, str] = {
            all_creators_key: all_creators_key,
            creator: creator,
            member_id: member_id,
            key: key_name,
            cursor: cursor
        }

        expires_in: int = await self.get_expiration(key_name)
        if expires_in == -2:
            # Redis TTL returns -2 when the key does not exist
            return edge

        _LOGGER.debug('Getting channel data for cursor', extra=log_extra)
        node_data: dict[str, any] | None = await self.client.json().get(
            key
        )

        if not node_data:
            return edge

        expires_at: int = int(datetime.now(tz=UTC).timestamp()) + expires_in

        channel = Channel(**node_data['node'])
        edge.node = channel
        edge.expires_at = max(0, expires_at)

        _LOGGER.debug(
            'Got oldest channel',
            extra=log_extra | {'channel': channel.creator}
        )

        return edge

    async def add_oldest_channel_back(self, member_id: UUID, channel: Channel
                                      ) -> None:
        '''
        Add the oldest channel back to the list of channels. Does NOT
        store the channel in the cache.

        :param channel: the channel to add
        :returns: the number of channels in the cache
        '''

        if not isinstance(channel, Channel):
            channel = Channel(**channel)

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        await self.add_to_cache(member_id, channel)

        all_creators_key: str = ChannelCache.get_all_creators_key()
        data: list[tuple[str, str]] = await self.client.zrange(
            all_creators_key, 0, 0
        )

        add_timestamp: float = datetime.now(tz=UTC).timestamp()
        if data:
            oldest_channel_timestamp: str
            _, oldest_channel_timestamp = data[0]
            add_timestamp = oldest_channel_timestamp - 1

        key_name: str = ChannelCache.get_channel_key(
            member_id, channel.creator
        )
        await self.client.zadd(all_creators_key, {key_name: add_timestamp})
        _LOGGER.debug(
            'Added channel back to all_creators ordered set',
            extra={
                # all_creators_key: all_creators_key,
                # member_id: member_id,
                # channel: channel.creator,
            }
        )

    async def get_channel(self, member_id: UUID, creator: str
                          ) -> Edge[Channel] | None:
        '''
        Get a channel from the cache

        :param creator:
        :param member_id:
        :returns: Edge[Channel] if the channel is in the cache, None otherwise
        '''

        if not isinstance(creator, str):
            raise ValueError(f'Creator must be a string: {creator}')

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        cursor: str = ChannelCache.get_cursor(member_id, creator)
        return await self.get_channel_by_cursor(cursor)

    async def get_channel_by_cursor(self, cursor: str) -> Edge[Channel] | None:
        '''
        Get a channel from the cache based on its cursor

        :param cursor:
        :returns: Edge[Channel] if the channel is in the cache, None otherwise
        '''

        if not isinstance(cursor, str):
            raise ValueError(f'Cursor must be a string: {cursor}')

        key_name: str = ChannelCache.get_channel_key_for_cursor(cursor)

        log_data: dict[str, str] = {'cursor': cursor, 'key': key_name}

        _LOGGER.debug('Getting channel data for cursor', extra=log_data)

        node_data: dict[str, any] | None = await self.client.json().get(
            key_name
        )

        if not node_data:
            return None

        edge: Edge = Edge(**node_data)
        edge.node = Channel(**node_data['node'])

        return edge

    @staticmethod
    def parse_channel_key(key: str) -> tuple[UUID, str]:
        '''
        Parses the key for a JSON value with the channel data

        :param key: the key to parse, as is used in the creator lists
        :returns: the member_id and creator
        :raises: ValueError
        '''

        if not isinstance(key, str):
            raise ValueError(f'Key must be a string: {key}')

        if key.startswith(f'{ChannelCache.CHANNEL_KEY_PREFIX}:'):
            key = key[len(ChannelCache.CHANNEL_KEY_PREFIX) + 1:]

        member_id_string: str
        creator: str
        member_id_string, creator = key.split('_', 1)

        log_data: dict[str, str | UUID] = {
            'member_id': member_id_string,
            'creator': creator
        }
        _LOGGER.debug('Split cursor', extra=log_data)

        try:
            member_id: UUID = UUID(member_id_string)
            return member_id, creator
        except ValueError:
            _LOGGER.warning(f'Invalid member_id in cursor: {member_id_string}')
            raise

    @staticmethod
    def get_cursor(member_id: UUID, creator: str) -> str:
        '''
        Get the cursor for the channel

        :param member_id: the member that originated the channel
        :param creator: the channel to get the cursor for
        :returns: the cursor for the channel
        '''

        if not isinstance(creator, str):
            raise ValueError(f'Creator must be a string: {creator}')

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        return f'{member_id}_{creator}'

    async def add_to_cache(self, member_id: UUID, channel: Channel | dict
                           ) -> bool:
        '''
        Add channel to the cache. Does not update list of channels
        or set of channels.

        :param member_id:
        :param channel:
        :returns: True if the channel was added to the cache, False otherwise
        '''

        if not isinstance(channel, Channel):
            channel = Channel(**channel)

        if not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        key: str = ChannelCache.get_channel_key(
            member_id, channel.creator
        )

        channel_data: dict[str, any] = jsonable_encoder(channel)
        cursor: str = ChannelCache.get_cursor(member_id, channel.creator)

        edge_data: dict[str, any] = {
            'cursor': cursor,
            'origin': str(member_id),
            'node': channel_data
        }

        _LOGGER.debug(f'Setting channel data for key: {key}')

        result: bool = await self.client.json().set(
            key, '.', edge_data
        )

        if not result:
            return False

        await self.set_expiration(key)

        await self.set_shortcut(member_id, channel.creator)

        return True

    @staticmethod
    def get_shortcut_value(member_id: UUID, creator: str) -> str:
        '''
        Get the value for the shortcut

        :param member_id: the member_id of the creator
        :param creator: the name of the creator/channel
        :returns: the shortcut value
        '''

        unencoded: bytes = ChannelCache.get_cursor(
            member_id, creator
        ).encode('utf-8')
        encoded: str = base64.b64encode(unencoded).decode('utf-8')[0:12]

        return encoded

    @staticmethod
    def get_shortcut_key(member_id: UUID, creator: str) -> str:
        '''
        Gets the cache key for the shortcut

        :param member_id: the member_id of the creator
        :param creator: the name of the creator/channel
        :returns: the shortcut value
        '''

        encoded: str = ChannelCache.get_shortcut_value(member_id, creator)
        return f'{ChannelCache.CHANNEL_SHORTCUT_PREFIX}:{encoded}'

    async def set_shortcut(self, member_id: UUID, creator: str) -> str:
        '''
        Sets a shortcut for the channel in the cache

        :param member_id: the member_id of the creator
        :param creator: the name of the creator/channel
        :returns: the shortcut
        '''

        shortcut_key: str = ChannelCache.get_shortcut_key(member_id, creator)
        encoded_shortcut: str = f'{member_id}_{creator}'
        _LOGGER.debug(
            'Setting channel shortcut',
            {
                'shortcut_key': shortcut_key,
                'shortcut_value': encoded_shortcut,
                'member_id': member_id,
                'creator': creator,
            }
        )
        await self.client.set(
            shortcut_key, encoded_shortcut,
            ex=ChannelCache.CHANNEL_SHORTCUT_EXPIRATION
        )

    async def get_shortcut(self, shortcut: str) -> tuple[UUID, str]:
        '''
        Gets the member_id and creator/channel name for the shortcut

        :param shortcut: the shortcut
        :returns: member_id and creator/channel name
        '''

        shortcut_key: str = \
            f'{ChannelCache.CHANNEL_SHORTCUT_PREFIX}:{shortcut}'

        value: any = await self.client.get(shortcut_key)

        # If a shortcut is being used then we extend its expiration
        await self.client.expire(
            shortcut_key, time=timedelta(
                seconds=self.CHANNEL_SHORTCUT_EXPIRATION
            )
        )

        log_data: dict[str, any] = {
            'shortcut': shortcut,
            'shortcut_key': shortcut_key,
            'shortcut_value': value
        }

        if not value:
            raise FileNotFoundError

        if not isinstance(value, str):
            _LOGGER.debug('Shortcut value is not a string', extra=log_data)
            raise ValueError('Value for key is not a string')

        if len(value) < 38:
            _LOGGER.debug('Value for key too short', extra=log_data)
            raise ValueError('Invalid value for shortcut key')

        member_id: UUID = UUID(value[:36])
        creator: str = value[37:]

        log_data['member_id'] = member_id
        log_data['creator'] = creator
        _LOGGER.debug('Shortcut found', log_data)

        return (member_id, creator)

    def setup_metrics(self) -> None:
        '''
        Set up the metrics for the cache

        :returns: None
        '''

        metrics: dict[str, Gauge, Counter] = config.metrics

        metric: str = 'channelcache_total_channels'
        if metric in metrics:
            return

        metrics[metric] = Gauge(
            metric, 'Total number of channels in the cache'
        )

    async def in_cache(self, member_id: UUID, creator: str) -> bool:
        '''
        Check if an asset is in the cache.

        :param member_id: The member that originated the asset.
        :param channel_id: The channel to check.
        :return: True if the asset is in the cache, False otherwise.
        :raises: None
        '''

        server_cursor: str = ChannelCache.get_cursor(member_id, creator)

        item_key: str = ChannelCache.CHANNEL_KEY_PREFIX + server_cursor

        return await self.client.exists(item_key)
