'''
Asset lists are lists of assets stored in the AssetCache

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from uuid import UUID

from redis import Redis

from prometheus_client import Counter
from prometheus_client import Gauge

from byoda import config


class AssetList:
    IN_HEAD_LIST_LEN: int = 20
    LISTS_KEY_PREFIX: str = 'lists:'
    DEFAULT_EXPIRATION: int = 90 * 86400

    def __init__(self, list_name: str, is_internal: bool = False,
                 redis: Redis | None = None) -> None:
        self.name: str = list_name
        self.is_internal: bool = is_internal

        self.redis_key: str = self.get_key(list_name, is_internal=is_internal)

        self.redis: Redis | None = redis

        self.setup_metrics()

    def setup_metrics(self) -> None:
        metrics: dict[str, Gauge | Counter] = config.metrics

        metric: str = 'asset_list_node_not_found'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'the node for a cursor in a list was not found in '
                    'the cache'
                )
            )

        metric: str = 'asset_list_creator_in_head_of_list'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'a creator of an asset already has another asset in the '
                    'head of the list'
                )
            )

        metric = 'asset_list_creator_not_in_head_of_list'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'a creator of an asset does not have another '
                    'asset in the head of the list'
                )
            )

        metric: str = 'asset_list_contains_cursor'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'the asset_list already contains the cursor'
                )
            )

        metric: str = 'asset_list_does_not_contain_cursor'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'the asset list does not contain the cursor'
                )
            )

        metric: str = 'asset_list_add_asset'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'an asset was added to an asset list'
                )
            )

        metric: str = 'asset_list_delete_asset'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'an asset was deleted from an asset list'
                )
            )

    @staticmethod
    def get_key(list_name: str, member_id: UUID | str | None = None,
                is_internal: bool = False) -> str:
        '''
        Get the Redis key for the list of assets

        :param list_name: The name of the list of assets
        :returns: The Redis key for the list
        '''

        if member_id and not isinstance(member_id, UUID):
            member_id = UUID(member_id)

        if not isinstance(list_name, str):
            raise ValueError(
                'List name must be a string', extra={'list': list_name}
            )

        if is_internal:
            return f'_{AssetList.LISTS_KEY_PREFIX}{list_name}'
        else:
            return f'{AssetList.LISTS_KEY_PREFIX}{list_name}'

    async def exists(self) -> bool:
        if await self.redis.exists(self.redis_key):
            return True

        return False

    async def contains_cursor(self, cursor: str) -> bool:
        return bool(await self.redis.zrank(self.redis_key, cursor))

    async def add(self, cursor: str, expires_at: int | float,
                  to_back: bool = False) -> None:
        '''
        Adds an asset to the list

        :param cursor: The cursor of the asset
        :param expires_at: The timestamp the asset expires
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        metrics['asset_list_add_asset'].inc()

        await self.redis.zadd(self.redis_key, {cursor: expires_at})

    async def delete(self) -> bool:
        '''
        Deletes the list from the cache

        :returns: whether the list existed in the cache
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        if await self.redis.delete(self.redis_key, self.redis_key):
            metrics['asset_list_delete_asset'].inc()
            return True

        return False

    async def remove(self, cursor: str) -> None:
        '''
        Removes an asset from the list

        :param cursor: The cursor of the asset
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics
        metrics['asset_list_delete_asset'].inc()

        await self.redis.zrem(self.redis_key, cursor)

    async def in_head(self, creator: str) -> bool:
        '''
        Check if the first 20 assets in the list were created by a given
        creator. This helps preventing that multiple assets of a creator show
        up in the head of a list

        :param creator: The creator to check
        :returns: True if the creator has assets in the head of the list,
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics

        head_cursors: list = await self.redis.zrange(
            self.redis_key, 1 - AssetList.IN_HEAD_LIST_LEN, -1
        )
        for cursor in head_cursors:
            asset: dict[str, dict[str, any]] = await self.redis.json().get(
                cursor
            )
            if not asset or not asset['node']:
                metrics['asset_list_node_not_found'].inc()
                await self.remove(cursor)
                continue

            if asset['node']['creator'] == creator:
                metrics['asset_list_creator_in_head_of_list'].inc()
                return True

        metrics['asset_list_creator_not_in_head_of_list'].inc()
        return False

    def is_channel_list(self) -> bool:
        '''
        Check if a list is a channel list

        :param list_name: the name of the list to check
        :returns: True if the list is a channel list, False otherwise
        '''

        if len(self.name) < 36 or self.name[36] != '_':
            return False

        try:
            UUID(self.name[:36])
        except ValueError:
            return False

        return True

    async def set_expiration(self, ttl: int = DEFAULT_EXPIRATION) -> None:
        '''
        Sets the expiration time for the list

        '''

        await self.redis.expire(self.redis_key, ttl)

    async def length(self) -> int:
        '''
        Returns the length of the list

        :returns: The length of the list
        '''

        return await self.redis.zcard(self.redis_key)