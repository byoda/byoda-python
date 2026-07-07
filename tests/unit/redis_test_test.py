#!/usr/bin/env python3

import unittest

from redis import Redis

import redis.asyncio as redis

from tests.lib.redis_server import flush_redis
from tests.lib.redis_server import redis_url


class TestRedis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        flush_redis(db=0)

    async def test_list_roundtrip(self) -> None:
        client: Redis[any] = redis.from_url(
            redis_url(db=0, decode_responses=True)
        )
        try:
            list_name: str = 'mylist'
            values: list[int] = [i for i in range(10000)]
            await client.delete(list_name)
            await client.rpush(list_name, *values[0:2])
            res: list | None = await client.lrange(list_name, 0, -1)
            self.assertEqual(res, ['0', '1'])
        finally:
            await client.aclose()


if __name__ == '__main__':
    unittest.main()
