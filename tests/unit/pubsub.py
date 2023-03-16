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


_LOGGER = logging.getLogger(__name__)

TEST_DIR = '/tmp/byoda-tests/pubsub'


class TestPubSub(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

    async def test_object(self):
        connection_string = f'ipc:///{TEST_DIR}/test.ipc'

        data = {'test': 'test'}

        with pynng.Pub0(listen=connection_string) as pub, \
                pynng.Sub0(dial=connection_string) as sub:
            sub.subscribe(b'')
            pub.send(orjson.dumps(data))

            result = sub.recv()
            val = orjson.loads(result)
            self.assertEqual(data, val)

        pub = PubSub.setup('test', True, PubSubTech.NNG)
        sub = PubSub.setup('test', False, PubSubTech.NNG)
        await pub.send(data)
        val = await sub.recv()
        self.assertEqual(val, data)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
