#!/usr/bin/env python3

'''
Test cases for Queue implemented on top of Redis

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import unittest

from anyio import sleep
from anyio import create_task_group
from anyio import TASK_STATUS_IGNORED
from anyio.abc import TaskStatus


from byoda.storage.message_queue import Queue, QueueMessage

REDIS_URL: str = 'redis://192.168.1.13:6379/0'

TEST_QUEUE: str = 'testqueue'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        queue = await Queue.setup(REDIS_URL)
        key: str = queue.get_key(TEST_QUEUE)
        await queue.queue.delete(key)
        await queue.queue.aclose()

    async def asyncTearDown(self) -> None:
        pass

    async def test_queue(self) -> None:
        queue = await Queue.setup(REDIS_URL)
        async with create_task_group() as tg:
            await tg.start(queue_listener, queue, TEST_QUEUE)
            await sleep(1)
            message = QueueMessage(1, 'testcase', 'test-message')
            tg.start_soon(push_message, queue, TEST_QUEUE, message)

        await queue.queue.aclose()


async def push_message(queue: Queue, test_key: str, message: QueueMessage
                       ) -> None:
    await queue.push(test_key, message)


async def queue_listener(queue: Queue, key: str, *, task_status:
                         TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
    task_status.started()
    message: QueueMessage = await queue.bpop(key)
    print(
        f'Got message from {message.sender} version: {message.version}: '
        f'{message.contents}'
    )


if __name__ == '__main__':
    unittest.main()
