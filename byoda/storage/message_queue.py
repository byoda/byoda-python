'''
Manage message queue

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from typing import Self
from logging import getLogger

import orjson

from redis import Redis
import redis.asyncio as redis

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)


class QueueMessage:
    def __init__(self, version: int, sender: str, contents: dict[str, any]
                 ) -> None:
        self.version: int = version
        self.sender: str = sender
        self.contents: any = contents

    def __str__(self) -> str:
        return orjson.dumps(self.__dict__).decode('utf-8')


class Queue:
    KEY_PREFIX: str = 'queues:'

    def __init__(self, connection_string: str) -> None:
        self.connection_string: str = connection_string
        self.queue: Redis | None = None

    @staticmethod
    async def setup(connection_string: str) -> Self:
        queue = Queue(connection_string)
        queue.queue = redis.from_url(
            connection_string, decode_responses=True, protocol=3
        )
        return queue

    async def close(self) -> None:
        await self.queue.aclose()

    def get_key(self, queue_name: str) -> str:
        return f'{self.KEY_PREFIX}{queue_name}'

    async def push(self, queue_name: str, message: QueueMessage) -> None:
        '''
        Pushes a message onto the queue

        :param queue_name: The name of the queue
        :param message: The message to push
        :returns: (none)
        '''

        key: str = self.get_key(queue_name)

        await self.queue.lpush(key, str(message))

    async def bpop(self, queue_name: str) -> QueueMessage:
        key: str = f'{self.KEY_PREFIX}{queue_name}'

        message: str
        _, message = await self.queue.brpop(key)

        data: dict[str, any] = orjson.loads(message)

        msg = QueueMessage(**data)

        return msg
