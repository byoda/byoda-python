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
import asyncio
import logging

import pynng

import orjson

from byoda.datatypes import PubSubTech

_LOGGER = logging.getLogger(__name__)


class PubSub:
    def __init__(self, connection_string: str, service_id: int,
                 is_sender: bool):
        self.connection_string: str = connection_string
        self.service_id: int = service_id
        self.is_sender: bool = is_sender
        self.pub: pynng.Pub0 | None = None
        self.subs: list[pynng.Sub0] = []

    @staticmethod
    def setup(connection_string: str, service_id: int,
              is_counter: bool = False, is_sender: bool = False,
              pubsub_tech: PubSubTech = PubSubTech.NNG):
        '''
        Factory for PubSub
        '''

        if pubsub_tech == PubSubTech.NNG:
            return PubSubNng(
                connection_string, service_id, is_counter, is_sender
            )
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

    def __init__(self, class_name: str, service_id: int, is_counter: bool,
                 is_sender: bool):
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

        self.work_dir = PubSubNng.PUBSUB_DIR

        connection_string = PubSubNng.get_connection_string(
            class_name, service_id, is_counter
        )

        path = PubSubNng.get_directory(service_id)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)

        super().__init__(connection_string, service_id, is_sender)

        if self.is_sender:
            _LOGGER.debug(
                f'Setting up for sending to {self.connection_string}'
            )
            try:
                self.pub = pynng.Pub0(listen=self.connection_string)
            except pynng.exceptions.AddressInUse:
                _LOGGER.exception(f'Address in use: {self.connection_string}')
                raise

            self.pub.send_timeout = self.SEND_TIMEOUT
            self.pub.send_buffer_size = self.SEND_BUFFER_SIZE
            self.sub: pynng.Sub0 | None = None
        else:
            _LOGGER.debug(
                f'Setting up for receiving messages for class {class_name}'
            )

            path = PubSubNng.get_directory(service_id)
            files = os.listdir(path)
            for file in files:
                prefix = PubSubNng.get_filename(class_name, is_counter)
                if file.startswith(prefix):
                    filepath = PubSubNng.get_connection_string(
                        class_name, service_id, is_counter
                    )
                    _LOGGER.debug(
                        f'Found file: {file} for class {class_name}'
                    )
                    sub = pynng.Sub0(dial=filepath)
                    sub.subscribe(b'')
                    self.subs.append(sub)

    @staticmethod
    def get_directory(service_id: int) -> str:
        '''
        Gets the directory in which the special files are created for the
        service
        '''

        return f'{PubSubNng.PUBSUB_DIR}/service-{service_id}'

    @classmethod
    def get_connection_prefix(cls, class_name: str, service_id: int,
                              is_counter: bool) -> str:
        '''
        Gets the file/path for the special file without the process ID suffix
        '''

        path = cls.get_directory(service_id)
        filename = cls.get_filename(class_name, is_counter)
        filepath = f'ipc://{path}/{filename}'

        return filepath

    @staticmethod
    def get_filename(class_name: str, is_counter: bool) -> str:
        filename = f'{class_name}.pipe-'
        if is_counter:
            filename += 'COUNTER-'

        return filename

    @classmethod
    def get_connection_string(cls, class_name: str, service_id: int,
                              is_counter: bool) -> str:
        '''
        Gets the file/path for the special file

        The filename includes the ID of the calling process so we can
        support senders to run multiple webserver processes to run in
        parallel, as nng does not support multiple senders to the same
        socket.
        Readers will have to read from all the files for the service_id
        & class_name in order to get all the messages for the class
        '''

        filepath = cls.get_connection_prefix(
            class_name, service_id, is_counter
        )
        return f'{filepath}{os.getpid()}'

    @staticmethod
    def cleanup():
        '''
        Deletes the directory where the special files are stored
        '''

        shutil.rmtree(PubSubNng.PUBSUB_DIR, ignore_errors=True)

    async def send(self, data: object):
        if not self.pub:
            raise ValueError('PubSubNng not setup for sending')

        val = orjson.dumps(data)
        await self.pub.asend(val)

    async def recv(self) -> list[object]:
        if not self.subs:
            raise ValueError('PubSubNng not setup for receiving')

        tasks = [
            asyncio.create_task(sub.arecv())
            for sub in self.subs
        ]

        completed_tasks = asyncio.as_completed(tasks)

        data = [
            orjson.loads(await completed_task)
            for completed_task in completed_tasks
        ]

        return data
