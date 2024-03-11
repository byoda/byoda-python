'''
Test sending verification and password reset emails.

This test needs a running email_worker.py

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import os
import sys
import socket
import unittest

from datetime import UTC
from datetime import datetime
from yaml import safe_load
from unittest import IsolatedAsyncioTestCase

import redis.asyncio as redis

from byoda.storage.message_queue import Queue

from byoda.util.logger import Logger

from byoda import config

from byotubesvr.datamodel.email import EmailVerificationMessage

CONFIG_FILE: str = 'config-byotube.yml'

QUEUE: Queue | None = None


class Test(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config_file: str = os.environ.get('CONFIG_FILE', CONFIG_FILE)
        with open(config_file) as file_desc:
            svc_config: dict[str, dict[str, any]] = safe_load(file_desc)
            connection_string: str = \
                svc_config['svcserver']['asset_cache_readwrite']

        config.debug = True

        if '192.168.' not in svc_config['svcserver']['asset_cache_readwrite']:
            raise ValueError(
                'We must use a local Redis server for testing'
            )

        queue = Queue(connection_string)
        queue.queue = redis.from_url(
            connection_string, decode_responses=True, protocol=3
        )
        global QUEUE
        QUEUE = queue

    async def asyncTearDown(self):
        await QUEUE.queue.aclose()

    async def test_create_verification_email(self) -> None:
        queue: Queue = QUEUE
        now: datetime = datetime.now(tz=UTC)
        email: EmailVerificationMessage = EmailVerificationMessage(
            sender='tests/func/worker_email.py',
            subject=f'Test verification email at {now}',
            recipient_name='Test User',
            recipient_email='test@byoda.org',
            sender_address='DoNotReply@byo.tube',
            verification_url='https://api.byo.tube/api/v1/lite/verify?',
        )
        await email.to_queue(queue)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result: int = sock.connect_ex(('127.0.0.1', 5020))
    if result != 0:
        raise RuntimeError(
            'These websocket tests need a running pod server on port 8000'
        )

    unittest.main()
