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
        _LOGGER.debug('test_pyng_one_sender_one_receiver')
        connection_string = f'ipc:///{TEST_DIR}/test.ipc'

        data = {'test': 'test'}

        # Test native pynng
        with pynng.Pub0(listen=connection_string) as pub, \
                pynng.Sub0(dial=connection_string) as sub:
            sub.subscribe(b'')
            pub.send(orjson.dumps(data))

            result = sub.recv()
            val = orjson.loads(result)
            self.assertEqual(data, val)

    async def test_pynng_two_senders_two_receiver(self):
        _LOGGER.debug('test_pyng_one_sender_one_receiver')
        connection_string_one = f'ipc:///{TEST_DIR}/test_one.ipc'
        connection_string_two = f'ipc:///{TEST_DIR}/test_two.ipc'

        data_one = {'test': 'test'}
        data_two = {'test_two': 'test_two'}

        pub_one = pynng.Pub0(listen=connection_string_one)
        pub_two = pynng.Pub0(listen=connection_string_two)

        sub_one = pynng.Sub0(dial=connection_string_one)
        sub_one.subscribe(b'')
        sub_two = pynng.Sub0(dial=connection_string_two)
        sub_two.subscribe(b'')

        pub_one.send(orjson.dumps(data_one))
        pub_two.send(orjson.dumps(data_two))

        result_one = sub_one.recv()
        result_two = sub_two.recv()

        val_one = orjson.loads(result_one)
        self.assertEqual(data_one, val_one)
        val_two = orjson.loads(result_two)
        self.assertEqual(data_two, val_two)

    async def test_one_sender_one_receiver(self):
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
        val = await sub.recv()
        self.assertEqual(val[0], data)

    async def test_one_sender_two_receivers(self):
        _LOGGER.debug('test_one_sender_two_receivers')
        data = {'test': 'test'}

        pub = PubSub.setup(
            'test', 999, is_counter=False, is_sender=True,
            pubsub_tech=PubSubTech.NNG
        )
        sub = PubSub.setup(
            'test', 999, is_counter=False, is_sender=False,
            pubsub_tech=PubSubTech.NNG
        )

        sub2 = PubSub.setup(
            'test', 999, is_counter=False, is_sender=False,
            pubsub_tech=PubSubTech.NNG
        )

        await pub.send(data)
        val = await sub.recv()
        self.assertEqual(val[0], data)

        val = await sub2.recv()
        self.assertEqual(val[0], data)

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
