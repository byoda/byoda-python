'''
Test sending verification and password reset emails.

This test needs a running email_worker.py

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import os
import sys
import unittest

from datetime import UTC
from datetime import datetime
from logging import Logger

from yaml import safe_load
from unittest import IsolatedAsyncioTestCase

import httpx

from anyio import sleep

import redis.asyncio as redis

from byoda.storage.message_queue import Queue

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from byotubesvr.datamodel.email import EmailVerificationMessage

CONFIG_FILE: str = 'config-byotube.yml'

QUEUE: Queue | None = None


class Test(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
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

    async def asyncTearDown(self) -> None:
        await QUEUE.queue.aclose()

    async def test_create_verification_email(self) -> None:
        mails_sent: int = get_mails_sent()
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

        await sleep(5)
        mails_sent_now: int = get_mails_sent()
        self.assertEqual(mails_sent_now, mails_sent + 1)


def get_mails_sent() -> int:
    resp: httpx.Response = httpx.get('http://localhost:5020/metrics')
    if resp.status_code != 200:
        raise ValueError('Email worker not running')
    mails_sent: int | None = None
    for line in resp.text.splitlines():
        print(line)
        if line.startswith('mail_worker_sent_emails'):
            print(line)
            mails_sent = int(float(line.split(' ')[-1]))
            return mails_sent

    # At startup, the email_worker does not have a value yet for the
    # counter so it does not get included in the output of the exporter
    return 0


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )

    unittest.main()
