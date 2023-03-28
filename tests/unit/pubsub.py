'''
Test cases for PubSub

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import shutil
import logging
import unittest

import pynng
import orjson

from byoda.util.logger import Logger

from byoda.datatypes import PubSubTech
from byoda.storage.pubsub import PubSub
from byoda.storage.pubsub import PubSubNng


_LOGGER = logging.getLogger(__name__)

TEST_DIR = '/tmp/byoda-tests/pubsub'
SERVICE_ID = 999


class TestPubSub(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            path = PubSubNng.get_directory(service_id=SERVICE_ID)
            shutil.rmtree(path)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR, exist_ok=True)

    async def test_pynng_one_sender_one_receiver(self):
        _LOGGER.debug('test_pynng_one_sender_one_receiver')
        connection_string = f'ipc:///{TEST_DIR}/test.ipc'

        data = {'test': 'test'}

        # Test native pynng
        with pynng.Pub0(listen=connection_string) as pub, \
                pynng.Sub0(dial=connection_string) as sub:
            sub.subscribe(b'')
            pub.send(orjson.dumps(data))

            result = sub.recv()
            value = orjson.loads(result)
            self.assertEqual(data, value)

    async def test_pynng_two_senders_two_receiver(self):
        _LOGGER.debug('test_pynng_two_senders_two_receivers')
        connection_strings = [
            f'ipc:///{TEST_DIR}/test_one.ipc',
            f'ipc:///{TEST_DIR}/test_two.ipc'
        ]

        data = [{'test': 'test'}, {'test_two': 'test_two'}]

        pubs = [
            pynng.Pub0(listen=connection_strings[0]),
            pynng.Pub0(listen=connection_strings[1])
        ]

        subs = [
            pynng.Sub0(dial=connection_strings[0]),
            pynng.Sub0(dial=connection_strings[1])
        ]
        subs[0].subscribe(b'')
        subs[1].subscribe(b'')

        pubs[0].send(orjson.dumps(data[0]))
        pubs[1].send(orjson.dumps(data[1]))

        results = [subs[0].recv(), subs[1].recv()]

        values = [
            orjson.loads(results[0]),
            orjson.loads(results[1])
        ]
        self.assertEqual(data[0], values[0])

        self.assertEqual(data[1], values[1])

    async def test_one_sender_one_receiver(self):
        _LOGGER.debug('test_one_sender_one_receiver')
        data = {'test': 'test'}

        pub = PubSub.setup(
            'test', 999, is_counter=False, is_sender=True,
            pubsub_tech=PubSubTech.NNG
        )

        sub = PubSub.setup(
            'test', 999, is_counter=False, is_sender=False,
            pubsub_tech=PubSubTech.NNG
        )

        await pub.send(data)
        values = await sub.recv()
        self.assertEqual(values[0], data)

    async def test_one_sender_two_receivers(self):
        _LOGGER.debug('test_one_sender_two_receivers')
        data = {'test': 'test'}

        pub = PubSub.setup(
            'test', 999, is_counter=False, is_sender=True,
            pubsub_tech=PubSubTech.NNG
        )

        subs = [
            PubSub.setup(
                'test', 999, is_counter=False, is_sender=False,
                pubsub_tech=PubSubTech.NNG
            ),
            PubSub.setup(
                'test', 999, is_counter=False, is_sender=False,
                pubsub_tech=PubSubTech.NNG
            )
        ]

        await pub.send(data)
        values = [
            await subs[0].recv(),
            await subs[1].recv()
        ]
        self.assertEqual(values[0][0], data)
        self.assertEqual(values[1][0], data)

    async def test_two_senders_one_receiver(self):
        _LOGGER.debug('test_two_senders_one_receiver')

        data = [{'test': 'test'}, {'test_two': 'test_two'}]

        pubs = [
            PubSub.setup(
                'test', 999, is_counter=False, is_sender=True,
                pubsub_tech=PubSubTech.NNG
            ),
            PubSubNng(
                'test', 999, is_counter=False, is_sender=True,
                process_id=1
            ),
        ]

        sub = PubSub.setup(
            'test', 999, is_counter=False, is_sender=False,
            pubsub_tech=PubSubTech.NNG
        )

        await pubs[0].send(data[0])
        await pubs[1].send(data[1])

        results = await sub.recv()

        for result in results:
            self.assertIn(result, data)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
