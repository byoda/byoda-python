'''
Test cases for the channel cache API on the byotube server

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023, 2024, 2024
:license    : GPLv3
'''

import os
import sys
import unittest

from uuid import UUID
from datetime import UTC
from datetime import datetime

from byoda.datacache.channel_cache import ChannelCache

from byoda.models.data_api_models import Channel
from byoda.models.data_api_models import EdgeResponse as Edge

from byoda.util.logger import Logger

from tests.lib.util import get_test_uuid

REDIS_URL: str = os.getenv('REDIS_URL', 'redis://192.168.1.13:6379')

CHANNEL_CACHE: ChannelCache | None = None


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        cache = await ChannelCache.setup(REDIS_URL)
        await cache.client.flushdb()
        await cache.client.function_flush('SYNC')
        try:
            await cache.client.ft(cache.index_name).dropindex()
        except Exception:
            pass

        await cache.close()

        global CHANNEL_CACHE
        CHANNEL_CACHE = await ChannelCache.setup(REDIS_URL)

    async def asyncTearDown(self) -> None:
        await CHANNEL_CACHE.close()

    async def test_channel_cache(self) -> None:
        channel_cache: ChannelCache = CHANNEL_CACHE

        channel_id: UUID = get_test_uuid()
        created: datetime = datetime.now(tz=UTC)
        channel = Channel(
            channel_id=channel_id,
            creator='test_creator',
            created_timestamp=created,
            description='test channel',
            is_family_safe=True,
            keywords=['test', 'channel'],
        )
        member_id: UUID = get_test_uuid()
        await channel_cache.add_newest_channel(member_id, channel)

        set_key: str = channel_cache.get_set_key(ChannelCache.ALL_CREATORS)
        channel_key: str = ChannelCache.get_channel_key(
            member_id, channel.creator
        )
        result = await channel_cache.client.sismember(
            set_key, channel_key
        )
        self.assertTrue(result)

        edge: Edge | None = \
            await channel_cache.get_oldest_channel()

        self.assertTrue(edge is not None)

        result = await channel_cache.client.sismember(
            channel_cache.ALL_CREATORS, channel_key
        )
        self.assertFalse(result)

        await channel_cache.add_oldest_channel_back(member_id, channel)
        result = await channel_cache.client.sismember(
            set_key, channel_key
        )
        self.assertTrue(result)

        channel: Channel = edge.node

        self.assertEqual(channel.channel_id, channel_id)
        self.assertEqual(channel.created_timestamp, created)
        self.assertEqual(channel.description, 'test channel')
        self.assertEqual(channel.is_family_safe, True)
        self.assertEqual(channel.keywords, ['test', 'channel'])


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
