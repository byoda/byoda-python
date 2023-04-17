'''
PubSub using Nano Next Generation (NNG) as the underlying technology

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import shutil
import asyncio
import logging
from typing import TypeVar

import pynng

from byoda.datamodel.pubsub_message import PubSubMessage
from byoda.datamodel.pubsub_message import PubSubDataMessage

from .pubsub import PubSub

_LOGGER = logging.getLogger(__name__)

SchemaDataItem = TypeVar('SchemaDataItem')
Schema = TypeVar('Schema')


class PubSubNng(PubSub):
    SEND_TIMEOUT = 100
    RECV_TIMEOUT = 3660
    SEND_BUFFER_SIZE = 100
    PUBSUB_DIR = '/tmp/byoda-pubsub'

    def __init__(self, data_class: SchemaDataItem, schema: Schema,
                 is_counter: bool, is_sender: bool, process_id: int = None):
        '''
        This class uses local special files for inter-process
        communication. There is a file for each combination of:
        - server process
        - top-level data element of type 'array' in the service schema
        for changes to the data in that array
        - each top-level data element of type 'array' in the service schema
        for counting the number of elements in the array

        The filename format is:
            <prefix>/<process-id>.byoda_<data-element-name>[-count]

        :param data_class: The class for which data will be send or received
        :param service_id: the service id for which messages will be sent
        or received
        :param is_counter: the counter for the length of the array for
        <class_name>
        :param is_sender: is this instance going to send or receive messages
        :process_id: if specified, the full file/path to the seocker will
        use the provided process ID instead of the actual process ID. This
        parameter should only be used for testing purposes
        '''

        self.work_dir: str = PubSubNng.PUBSUB_DIR
        self.schema: Schema = schema

        connection_string: str = PubSubNng.get_connection_string(
            data_class.name, schema.service_id, is_counter, process_id
        )

        path = PubSubNng.get_directory(schema.service_id)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)

        super().__init__(connection_string, data_class, schema, is_sender)

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
                'Setting up for receiving messages for class '
                f'{self.data_class.name}'
            )

            path = PubSubNng.get_directory(schema.service_id)
            files = os.listdir(path)
            for file in files:
                prefix = PubSubNng.get_filename(data_class.name, is_counter)
                if file.startswith(prefix):
                    filepath = PubSubNng.get_connection_string(
                        data_class.name, schema.service_id, is_counter,
                        process_id
                    )
                    _LOGGER.debug(
                        f'Found file: {file} for class {self.data_class.name}'
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
                              is_counter: bool, process_id: int = None) -> str:
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

        if not process_id:
            process_id = os.getpid()

        return f'{filepath}{process_id}'

    @staticmethod
    def cleanup():
        '''
        Deletes the directory where the special files are stored
        '''

        shutil.rmtree(PubSubNng.PUBSUB_DIR, ignore_errors=True)

    async def send(self, message: PubSubMessage):
        '''
        Serializes the data and sends it to the socket
        '''

        if not self.pub:
            raise ValueError('PubSubNng not setup for sending')

        val = message.to_bytes()
        await self.pub.asend(val)

    async def recv(self) -> list[PubSubMessage]:
        '''
        Receives the data from the socket, normalizes it and returns it
        '''

        if not self.subs:
            raise ValueError('PubSubNng not setup for receiving')

        tasks = [
            asyncio.create_task(sub.arecv())
            for sub in self.subs
        ]

        completed_tasks = asyncio.as_completed(tasks)

        responses = [
            await completed_task
            for completed_task in completed_tasks
        ]

        messages: list[PubSubDataMessage] = []
        # Replace the data with the normalized data
        for data in responses:
            message = PubSubMessage.parse(data, self.schema)
            if self.data_class.name != message.class_name:
                raise ValueError(
                    f'Received message for class {data.get("class_name")} '
                    f'on pubsub channel for class {self.data_class.name}'
                )

            messages.append(message)

        return messages