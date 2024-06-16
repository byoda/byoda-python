#!/usr/bin/env python3

import asyncio

from redis import Redis

import redis.asyncio as redis

CONNECTION_STRING = 'redis://192.168.1.13:6379?protocol=3'


async def main() -> None:
    client: Redis[any] = redis.from_url(
        CONNECTION_STRING, decode_responses=True
    )
    list_name: str = 'mylist'
    values: list[int] = [i for i in range(10000)]
    await client.delete(list_name)
    await client.rpush(list_name, *values[0:2])
    res = await client.lrange(list_name, 0, -1)
    print(res)

if __name__ == '__main__':
    asyncio.run(main())
