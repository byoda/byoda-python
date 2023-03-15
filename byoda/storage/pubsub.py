'''
There is both a generic SQL class. The generic SQL class takes care
of converting the data schema of a service to a SQL table. Classes
for different SQL flavors and implementations should derive from
this class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import shutil
import logging

import orjson
import pynng

from byoda.datatypes import PubSubTech

_LOGGER = logging.getLogger(__name__)


class PubSub:
    def __init__(self, connection_string: str, send: bool,
                 work_dir: str = None):
        self.connection_string: str = connection_string
        self.sender: bool = send
        self.pub: pynng.Pub0 | None = None
        self.sub: pynng.Sub0 | None = None

    @staticmethod
    def setup(connection_string: str, send: bool,
              pubsub_tech: PubSubTech = PubSubTech.NNG,
              work_dir: str = None):
        '''
        Factory for PubSub
        '''

        if pubsub_tech == PubSubTech.NNG:
            return PubSubNng(connection_string, send, work_dir=work_dir)
        else:
            raise ValueError(f'Unknown PubSub tech: {pubsub_tech}')

    @staticmethod
    def get_connection_string() -> str:
        '''
        Returns the connection string
        '''

        raise NotImplementedError

    @staticmethod
    def cleanup():
        '''
        Cleans up any resources
        '''

        raise NotImplementedError


class PubSubNng(PubSub):
    SEND_TIMEOUT = 100
    RECV_TIMEOUT = 3660
    SEND_BUFFER_SIZE = 100
    PUBSUB_DIR = '/tmp/byoda-pubsub'

    def __init__(self, class_name: str, send: bool,
                 work_dir: str = None):
        '''
        This class uses local special files for inter-process
        communication. There is a file for:
        - each server process
        - each top-level data element of type 'array' in the service schema
        for changes to the data in that array
        - each top-level data element of type 'array' in the service schema
        for counting the number of elements in the array

        The filename format is:
            <prefix>/<process-id>.byoda_<data-element-name>[-count]
        '''

        if work_dir:
            self.work_dir = work_dir
        else:
            self.work_dir = PubSubNng.PUBSUB_DIR

        if not os.path.isdir(self.work_dir):
            os.makedirs(self.work_dir, exist_ok=True)

        connection_string = PubSubNng.get_connection_string(
            class_name, self.work_dir
        )
        super().__init__(connection_string, send)

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

    @staticmethod
    def get_connection_string(class_name: str, work_dir: str = None) -> str:
        '''
        Gets the file/path for the special file
        '''

        if not work_dir:
            work_dir = PubSubNng.PUBSUB_DIR

        return f'ipc://{work_dir}/{os.getpid()}-BYODA-{class_name}'

    @staticmethod
    def cleanup(work_dir: str = None):
        '''
        Deletes the directory where the special files are stored
        '''

        if not work_dir:
            work_dir = PubSubNng.PUBSUB_DIR

        shutil.rmtree(work_dir, ignore_errors=True)

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
