'''
The generic PubSub classes from which tech-specific classes should
derive

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from typing import TypeVar

import orjson

from byoda.datatypes import PubSubMessageType
from byoda.datatypes import PubSubMessageAction

_LOGGER = logging.getLogger(__name__)

SchemaDataItem = TypeVar('SchemaDataItem')
Schema = TypeVar('Schema')


class PubSubMessage():
    '''
    Generic class for PubSub messages
    '''

    def __init__(self, message_type: PubSubMessageType):
        self.type: PubSubMessageType = message_type

        # Used by PubSubDataMessage
        self.action: PubSubMessageAction | None = None
        self.class_name: str | None = None
        self.data_class: SchemaDataItem | None = None
        self.data: object | None = None

        # Complete dict with values for all attributes, as
        # parsed by PubSubMessage.parse()

    def to_bytes(self) -> bytes:
        '''
        Classes derived from PubSubMessage should override this method
        '''

        raise NotImplementedError

    def to_dict(self):
        '''
        Classes derived from PubSubMessage should override this method
        '''

        raise NotImplementedError

    @staticmethod
    def parse(message: bytes, schema: Schema = None):
        '''
        Factory parser for messages of all classes derived from PubSubMessage
        '''

        all_data = orjson.loads(message)

        if all_data['type'].lower() == PubSubMessageType.DATA.value:
            msg = PubSubDataMessage.parse(all_data, schema)
        else:
            _LOGGER.exception(f'Unknown message type: {all_data["type"]}')
            raise ValueError

        return msg

    def create(data: object):
        '''
        Factory for creating messages, all classes derived from PubSubMessage
        must implemented this method
        '''

        raise NotImplementedError


class PubSubDataMessage(PubSubMessage):
    def __init__(self, action: PubSubMessageAction):
        super().__init__(PubSubMessageType.DATA)
        self.action = action

    @staticmethod
    def parse(data: bytes, schema: Schema):
        data_dict = orjson.loads(data)
        action = PubSubMessageAction(data_dict['action'])
        msg = PubSubDataMessage(action)

        msg.data_class: SchemaDataItem = \
            schema.data_classes[data_dict['class_name']].referenced_class
        msg.class_name: str = msg.data_class.name

        msg.data = msg.data_class.normalize(data_dict.get('data'))

        return msg

    @staticmethod
    def create(action: PubSubMessageAction, data: object,
               data_class: SchemaDataItem):

        msg = PubSubDataMessage(action)
        msg.data_class: SchemaDataItem = data_class
        msg.class_name: str = data_class.name
        msg.data: dict[str, object] = data

        return msg

    def to_bytes(self):
        '''
        Serializes the message to a list of bytes
        '''

        data = {
            'type': self.type,
            'action': self.action,
            'class_name': self.class_name,
            'data': self.data
        }
        return orjson.dumps(data)
