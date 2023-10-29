'''
The generic PubSub classes from which tech-specific classes should
derive

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger

import pynng

from byoda.datatypes import PubSubTech

_LOGGER: Logger = getLogger(__name__)

SchemaDataItem = TypeVar('SchemaDataItem')
Schema = TypeVar('Schema')


class PubSub:
    __slots__ = [
        'connection_string', 'schema', 'service_id', 'is_sender', 'data_class',
        'pub', 'subs'
    ]

    def __init__(self, connection_string: str, data_class: SchemaDataItem,
                 schema: Schema, is_sender: bool):
        self.connection_string: str = connection_string
        self.schema: Schema = schema
        self.service_id: int = schema.service_id
        self.is_sender: bool = is_sender

        self.data_class: SchemaDataItem = data_class
        self.pub: pynng.Pub0 | None = None
        self.subs: list[pynng.Sub0] = []

        action: str = 'receiving from'
        if self.is_sender:
            action = 'sending to'

        _LOGGER.debug(f'Setup for {action} {self.connection_string}')

    @staticmethod
    def setup(connection_string: str, data_class: SchemaDataItem,
              service_id: int, is_counter: bool = False,
              is_sender: bool = False,
              pubsub_tech: PubSubTech = PubSubTech.NNG):
        '''
        Factory for PubSub
        '''

        if pubsub_tech == PubSubTech.NNG:
            from .pubsub_nng import PubSubNng

            return PubSubNng(
                data_class, service_id, is_counter,
                is_sender
            )
        else:
            raise ValueError(
                f'Unknown PubSub tech {pubsub_tech}: {connection_string}'
            )

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
