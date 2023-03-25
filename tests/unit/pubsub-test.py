'''
Test cases for PubSub

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import json
import asyncio
import unittest

import pynng


class TestPubSub(unittest.IsolatedAsyncioTestCase):
    async def test_pynng_two_senders_four_receivers(self):
        connection_string_one = f'ipc:///tmp/test_one.ipc'
        connection_string_two = f'ipc:///tmp/test_two.ipc'

        data = [{'test': 'test'}, {'test_two': 'test_two'}]

        pub = [
            pynng.Pub0(listen=connection_string_one),
            pynng.Pub0(listen=connection_string_two)
        ]
        subs = [
            pynng.Sub0(dial=connection_string_one),
            pynng.Sub0(dial=connection_string_two),
            pynng.Sub0(dial=connection_string_one),
            pynng.Sub0(dial=connection_string_two)
        ]

        for sub in subs:
            sub.subscribe(b'')

        pub[0].send(json.dumps(data[0]).encode('utf-8'))
        pub[1].send(json.dumps(data[1]).encode('utf-8'))

        results = [subs[0].recv(), subs[1].recv()]

        values = [json.loads(results[0]), json.loads(results[1])]
        self.assertIn(values[0], data)
        self.assertIn(values[1], data)

        tasks = [
            asyncio.create_task(subs[2].arecv()),
            asyncio.create_task(subs[3].arecv())
        ]

        completed_tasks = asyncio.as_completed(tasks)
        for completed_Task in completed_tasks:
            result = json.loads(await completed_Task)
            self.assertIn(result, data)


if __name__ == '__main__':
    unittest.main()
