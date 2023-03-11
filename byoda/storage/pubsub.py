'''
There is both a generic SQL class. The generic SQL class takes care
of converting the data schema of a service to a SQL table. Classes
for different SQL flavors and implementations should derive from
this class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

import orjson
import pynng

from byoda.datatypes import PubSubTech

_LOGGER = logging.getLogger(__name__)


class PubSub:
    def __init__(self, connection_string: str, send: bool):
        self.connection_string: str = connection_string
        self.sender: bool = send

    @staticmethod
    def setup(pubsub_tech: PubSubTech, connection_string: str, send: bool):
        '''
        Factory for PubSub
        '''

        if pubsub_tech == PubSubTech.NNG:
            return PubSubNng(connection_string, send)
        else:
            raise ValueError(f'Unknown PubSub tech: {pubsub_tech}')


class PubSubNng(PubSub):
    SEND_TIMEOUT = 100
    RECV_TIMEOUT = 3660
    SEND_BUFFER_SIZE = 100

    async def __aenter__(self):
        self.pub: pynng.Sub0 | None = None
        self.sub: pynng.Sub0 | None = None
        if self.sender:
            self.pub = pynng.Pub0(listen=self.connection_string)
            self.pub.send_timeout = self.SEND_TIMEOUT
            self.pub.send_buffer_size = self.SEND_BUFFER_SIZE
        else:
            self.sub = pynng.Sub0(dial=self.connection_string)
            self.sub.subscribe(b'')

        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.pub:
            self.pub.close()
        else:
            self.sub.close()

    async def send(self, data: object):
        if not self.pub:
            raise ValueError('PubSubNng not setup for sending')

        with self.pub as pub:
            val = orjson.dumps(data)
            await pub.asend(val)

    async def recv(self) -> object:
        if not self.sub:
            raise ValueError('PubSubNng not setup for receiving')

        with self.sub as sub:
            val = await sub.arecv()
            data = orjson.loads(val)
            return data
