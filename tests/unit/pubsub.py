'''
Test cases for PubSub

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest

from logging import getLogger

import pynng
import orjson

from datetime import datetime
from datetime import timezone

from byoda.datamodel.pubsub_message import PubSubDataAppendMessage
from byoda.datamodel.pubsub_message import PubSubDataDeleteMessage

from byoda.datamodel.schema import Schema
from byoda.datamodel.dataclass import SchemaDataItem

from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.storage.filestorage import FileStorage

from byoda.storage.pubsub import PubSub
from byoda.storage.pubsub_nng import PubSubNng

from byoda.util.logger import Logger

from byoda import config

from tests.lib.util import get_test_uuid

_LOGGER: Logger = getLogger(__name__)

TEST_DIR: str = '/tmp/byoda-tests/pubsub'
SERVICE_ID: int = 999


class TestPubSub(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            shutil.rmtree(TEST_DIR)
            shutil.rmtree(PubSubNng.PUBSUB_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR, exist_ok=True)

        shutil.copy2('tests/collateral/addressbook.json', TEST_DIR)

        config.test_case = 'TEST_CLIENT'

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

    async def test_one_sender_one_receiver_append(self):
        _LOGGER.debug('test_one_sender_one_receiver_append')

        storage: FileStorage = FileStorage(TEST_DIR)
        schema: Schema = await Schema.get_schema(
            'addressbook.json', storage, None, None,
            verify_contract_signatures=False
        )

        schema.get_data_classes()

        data_class: SchemaDataItem = schema.data_classes[MARKER_NETWORK_LINKS]

        test_data = {
            'member_id': get_test_uuid(),
            'relation': 'friend',
            'created_timestamp': datetime.now(tz=timezone.utc)
        }

        pub = PubSub.setup('test', data_class, schema, is_sender=True)

        sub = PubSub.setup('test', data_class, schema, is_sender=False)

        message: PubSubDataAppendMessage = PubSubDataAppendMessage.create(
            test_data, data_class, 'test1234'
            )
        await pub.send(message)
        values = await sub.recv()

        value: PubSubDataAppendMessage = values[0]
        self.assertEqual(value.data, test_data)

    async def test_one_sender_one_receiver_delete(self) -> None:
        _LOGGER.debug('test_one_sender_one_receiver_delete')

        storage: FileStorage = FileStorage(TEST_DIR)
        schema: Schema = await Schema.get_schema(
            'addressbook.json', storage, None, None,
            verify_contract_signatures=False
        )

        schema.get_data_classes()

        data_class: SchemaDataItem = schema.data_classes[MARKER_NETWORK_LINKS]

        test_data = 1

        pub = PubSub.setup('test', data_class, schema, is_sender=True)

        sub = PubSub.setup('test', data_class, schema, is_sender=False)

        message = PubSubDataDeleteMessage.create(
            test_data, data_class
        )
        await pub.send(message)
        values = await sub.recv()

        value: PubSubDataDeleteMessage = values[0]
        self.assertEqual(value.data, test_data)

    async def test_one_sender_two_receivers(self):
        _LOGGER.debug('test_one_sender_two_receivers')

        storage: FileStorage = FileStorage(TEST_DIR)
        schema: Schema = await Schema.get_schema(
            'addressbook.json', storage, None, None,
            verify_contract_signatures=False
        )

        schema.get_data_classes()

        data_class: SchemaDataItem = schema.data_classes[MARKER_NETWORK_LINKS]

        test_data = {
            'member_id': get_test_uuid(),
            'relation': 'friend',
            'created_timestamp': datetime.now(tz=timezone.utc)
        }

        pub = PubSub.setup('test', data_class, schema, is_sender=True)

        subs = [
            PubSub.setup('test', data_class, schema, is_sender=False),
            PubSub.setup('test', data_class, schema, is_sender=False)
        ]
        message: PubSubDataAppendMessage = PubSubDataAppendMessage.create(
            test_data, data_class, 'test1234'
        )
        await pub.send(message)
        messages: list[PubSubDataAppendMessage] = [
            await subs[0].recv(),
            await subs[1].recv()
        ]
        self.assertEqual(messages[0][0].data, test_data)
        self.assertEqual(messages[1][0].data, test_data)

    async def test_two_senders_one_receiver(self):
        _LOGGER.debug('test_two_senders_one_receiver')

        storage: FileStorage = FileStorage(TEST_DIR)
        schema: Schema = await Schema.get_schema(
            'addressbook.json', storage, None, None,
            verify_contract_signatures=False
        )

        schema.get_data_classes()

        data_class: SchemaDataItem = schema.data_classes[MARKER_NETWORK_LINKS]

        test_data = [
            {
                'member_id': get_test_uuid(),
                'relation': 'friend',
                'created_timestamp': datetime.now(tz=timezone.utc)
            },
            {
                'member_id': get_test_uuid(),
                'relation': 'family',
                'created_timestamp': datetime.now(tz=timezone.utc)
            }
        ]

        # For the second instance of pubs, we bypass PubSub.setup() and
        # directly call PubSubNng() so that we can set the process_id
        pubs = [
            PubSub.setup('test', data_class, schema, is_sender=True),
            PubSubNng(data_class, schema, False, is_sender=True, process_id=1),
        ]

        sub = PubSub.setup('test', data_class, schema, is_sender=False)

        test_messages: list[PubSubDataAppendMessage] = [
            PubSubDataAppendMessage.create(
                test_data[0], data_class, 'test1234'
            ),
            PubSubDataAppendMessage.create(
                test_data[1], data_class, 'test1234'
            )
        ]

        await pubs[0].send(test_messages[0])
        await pubs[1].send(test_messages[1])

        results = await sub.recv()

        for result in results:
            self.assertIn(result.data, test_data)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
