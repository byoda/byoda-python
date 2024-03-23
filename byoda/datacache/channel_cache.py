'''
Asset Cache maintains lists of channels

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from uuid import UUID
from typing import Self
from logging import getLogger

from fastapi.encoders import jsonable_encoder

from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.datamodel.metrics import Metrics

from byoda.datatypes import ItemType

from byoda.models.data_api_models import Channel
from byoda.models.data_api_models import VideoThumbnail
from byoda.models.data_api_models import ExternalLink
from byoda.util.logger import Logger

from byoda.datacache.searchable_cache import SearchableCache

from byoda import config

_LOGGER: Logger = getLogger(__name__)


class ChannelCache(SearchableCache, Metrics):
    CHANNEL_PREFIX: str = 'channels'
    ALL_CHANNELS_LIST: str = 'all_channels'
    ALL_CHANNELS_HASH: str = 'all_channels_hash'

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

    def get_channel_key(self, member_id: UUID, channel_id: str,
                        is_internal_list: bool = False) -> str:
        '''
        Get the key for the channel

        :param channel_name: the name of the channel
        :param is_internal_list: whether the channel is an internal list
        :returns: the key for the channel
        '''

        cursor: str = self.get_cursor(member_id, channel_id, ItemType.CHANNEL)

        if is_internal_list:
            return f'_{self.CHANNEL_PREFIX}:{cursor}'

        return f'{self.CHANNEL_PREFIX}:{cursor}'

    async def add_newest_channel(self, member_id: UUID, channel: Channel,
                                 keywords: list[str] = []) -> int:
        '''
        Add a channel to the cache

        :param channel: the channel to add
        :returns: number of lists the channel was added to
        '''

        if self.in_cache(member_id, channel.channel_id, ItemType.CHANNEL):
            key = self.get_channel_key()
            self.set_expiration(key)
            return 0

        self.add_to_cache(member_id, channel)

        # TODO: add channels to lists

        return 0

    async def add_to_cache(self, member_id: UUID, channel: Channel | dict
                           ) -> None:

        if isinstance(channel, dict):
            channel = Channel(**channel)

        key: str = self.get_channel_key(member_id, channel.channel_id)

        channel_data: dict[str, any] = jsonable_encoder(channel)
        cursor: str = self.get_cursor(
            member_id, channel.channel_id, ItemType.CHANNEL
        )

        edge_data: dict[str, any] = {
            'cursor': cursor,
            'origin': str(member_id),
            'node': channel_data
        }

        result: bool = await self.client.json().set(
            key, '.', edge_data
        )
        self.set_expiration(key)

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

    def store_in_cache(self, member_id: UUID, channel: Channel) -> None:
        '''
        Store the channel in the cache

        :param member_id: the member id
        :param channel: the channel to store
        :returns: None
        '''

        key: str = self.get_channel_key(member_id, channel.channel_id)
        self.set(key, channel)

        self.add_to_all_channels(channel)