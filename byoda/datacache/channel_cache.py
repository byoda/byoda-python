'''
Asset Cache maintains lists of channels

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from uuid import UUID
from typing import Self
from hashlib import sha256
from base64 import b64encode
from logging import getLogger
from datetime import timedelta

from fastapi.encoders import jsonable_encoder

from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.datamodel.metrics import Metrics

from byoda.models.data_api_models import Channel
from byoda.models.data_api_models import VideoThumbnail
from byoda.models.data_api_models import ExternalLink
from byoda.util.logger import Logger

from byoda.models.data_api_models import EdgeResponse as Edge

from byoda.datacache.searchable_cache import SearchableCache

from byoda import config

_LOGGER: Logger = getLogger(__name__)


class ChannelCache(SearchableCache, Metrics):
    CHANNEL_KEY_PREFIX: str = 'channels'

    def __init__(self, connection_string: str) -> None:
        '''
        Constructor for the ChannelCache class

        :param connection_string: the connection string for the cache
        '''

        super().__init__(connection_string)

        self.setup_metrics()

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

        key: str = f'{ChannelCache.CHANNEL_KEY_PREFIX}:{cursor}'

        if is_internal_list:
            key = f'_{key}'

        return key

    async def add_newest_channel(self, member_id: UUID, channel: Channel
                                 ) -> bool:
        '''
        Add a channel to the cache and to the list of all channels

        :param channel: the channel to add
        :returns: number of lists the channel was added to
        '''

        if await self.in_cache(member_id, channel.creator):
            key: str = ChannelCache.get_channel_key(member_id, channel.creator)
            await self.set_expiration(key)
            return 0

        result: bool = await self.add_to_cache(member_id, channel)

        # Check if channel is already in list of channels/creators
        channel_key: str = ChannelCache.get_channel_key(
            member_id, channel.creator
        )

        set_key: str = self.get_set_key(self.ALL_CREATORS)
        if await self.client.sismember(set_key, channel_key):
            return result

        await self.append_channel(member_id, channel)

        return result

    async def append_channel(self, member_id: UUID, channel: Channel
                             ) -> bool:
        '''
        Add a channel to the end of the list of all channels

        :param channel: the channel to add
        :returns: number of lists the channel was added to
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        channel_key: str = ChannelCache.get_channel_key(
            member_id, channel.creator
        )

        set_key: str = self.get_set_key(self.ALL_CREATORS)
        await self.client.sadd(set_key, channel_key)
        await self.client.expire(
            set_key, time=timedelta(seconds=self.DEFAULT_EXPIRATION_LISTS)
        )

        list_key: str = self.get_list_key(self.ALL_CREATORS)
        await self.client.rpush(list_key, channel_key)
        await self.client.expire(
            list_key, time=timedelta(seconds=self.DEFAULT_EXPIRATION_LISTS)
        )

        metric: str = 'channelcache_total_channels'
        metrics[metric].inc()

    async def get_oldest_channel(self) -> Edge[Channel] | None:
        '''
        Removes and returns the oldest channel in the cache

        :returns: the oldest channel in the cache
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        list_key: str = self.get_list_key(self.ALL_CREATORS)

        channel_key: str = await self.client.lpop(list_key)
        if not channel_key:
            return None

        metric: str = 'channelcache_total_channels'
        metrics[metric].dec()

        # As we removed the item from the list, we should also remove it
        # from the set
        set_key: str = self.get_set_key(self.ALL_CREATORS)
        await self.client.srem(set_key, channel_key)

        expires_in: int = await self.get_expiration(channel_key)

        _LOGGER.debug(f'Getting channel data for key: {channel_key}')
        node_data: dict[str, any] | None = await self.client.json().get(
            channel_key
        )
        if not node_data:
            return None

        channel: Channel = Channel(**node_data['node'])
        member_id: UUID = UUID(node_data['origin'])
        cursor: str = node_data['cursor']
        edge = Edge(
            cursor=cursor, node=channel, origin=member_id,
            expires_in=expires_in
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

        key: str = ChannelCache.get_channel_key(
            member_id, channel.creator
        )

        # Update expiration of the channel data
        await self.set_expiration(key)

        await self.append_channel(member_id, channel)

    @staticmethod
    def get_cursor(member_id: UUID, creator: str) -> str:
        '''
        Get the cursor for the channel

        :param member_id: the member that originated the channel
        :param creator: the channel to get the cursor for
        :returns: the cursor for the channel
        '''

        return f'{str(member_id)}_{creator}'

    async def add_to_cache(self, member_id: UUID, channel: Channel | dict
                           ) -> bool:
        '''
        Add channel to the cache. Does not update list of channels
        or set of channels.

        :param member_id:
        :param channel:
        :returns: True if the channel was added to the cache, False otherwise
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        if isinstance(channel, dict):
            channel = Channel(**channel)

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

        return True

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

