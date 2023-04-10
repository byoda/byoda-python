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

        msg_type: str = all_data['type'].lower()
        action: str = all_data['action'].lower()

        if msg_type == PubSubMessageType.DATA.value:
            if action == PubSubMessageAction.APPEND.value:
                msg = PubSubDataAppendMessage.parse(all_data, schema)
            elif action == PubSubMessageAction.DELETE.value:
                msg = PubSubDataDeleteMessage.parse(all_data, schema)
            else:
                _LOGGER.exception(f'Unknown message action: {action}')
                raise ValueError(f'Unknown message action: {action}')
        else:
            _LOGGER.exception(f'Unknown message type: {msg_type}')
            raise ValueError(f'Unknown message type: {msg_type}')

        return msg

    def create(data: object):
        '''
        Factory for creating messages, all classes derived from PubSubMessage
        must implemented this method
        '''

        raise NotImplementedError


class PubSubDataMessage(PubSubMessage):
    def __init__(self, action: PubSubMessageAction, data: object,
                 data_class: SchemaDataItem = None):
        super().__init__(PubSubMessageType.DATA)
        self.action = action
        self.data_class: SchemaDataItem = data_class
        self.data: dict[str, object] = data
        self.class_name: str | None = None
        if data_class:
            self.class_name: str = data_class.name

    @staticmethod
    def parse(data: bytes, schema: Schema):
        '''
        Parse a message received over pub/sub
        '''

        raise NotImplementedError

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


class PubSubDataAppendMessage(PubSubDataMessage):
    def __init__(self, data: object, data_class: SchemaDataItem = None):
        super().__init__(PubSubMessageAction.APPEND, data, data_class)

    @staticmethod
    def create(data: object, data_class: SchemaDataItem):
        '''
        Factory
        '''

        msg = PubSubDataAppendMessage(data, data_class)

        return msg

    @staticmethod
    def parse(data: bytes | dict, schema: Schema):
        '''
        Factory, parses a message received over pub/sub

        :param data: either a list of bytes of JSON data or a dict
        :param schema: the schema for the service for which the message
        was received
        :returns: PubSubDataDeleteMessage
        :raises: ValueError
        '''

        if isinstance(data, bytes):
            data_dict = orjson.loads(data)
        elif isinstance(data, dict):
            data_dict = data
        else:
            _LOGGER.exception(
                f'Data provided is not a dict or bytes: {type(data)}'
            )
            raise ValueError(
                f'Data provided is not a dict or bytes: {type(data)}'
            )

        action = PubSubMessageAction(data_dict['action'])
        if action != PubSubMessageAction.APPEND:
            _LOGGER.exception(f'Invalid action: {action} for this class')
            raise ValueError

        msg = PubSubDataAppendMessage(data_dict)

        msg.data_class: SchemaDataItem = \
            schema.data_classes[data_dict['class_name']].referenced_class
        msg.class_name: str = msg.data_class.name

        msg.data = msg.data_class.normalize(data_dict.get('data'))

        return msg


class PubSubDataDeleteMessage(PubSubDataMessage):
    def __init__(self, data: object, data_class: SchemaDataItem = None):
        super().__init__(PubSubMessageAction.DELETE, data, data_class)

    @staticmethod
    def create(data: object, data_class: SchemaDataItem):
        '''
        Factory
        '''

        msg = PubSubDataDeleteMessage(data, data_class)

        return msg

    @staticmethod
    def parse(data: bytes | dict, schema: Schema):
        '''
        Factory, parses a message received over pub/sub

        :param data: either a list of bytes of JSON data or a dict
        :param schema: the schema for the service for which the message
        was received
        :returns: PubSubDataDeleteMessage
        :raises: ValueError
        '''

        if isinstance(data, bytes):
            data_dict = orjson.loads(data)
        elif isinstance(data, dict):
            data_dict = data
        else:
            _LOGGER.exception(
                f'Data provided is not a dict or bytes: {type(data)}'
            )
            raise ValueError(
                f'Data provided is not a dict or bytes: {type(data)}'
            )

        action = PubSubMessageAction(data_dict['action'])
        if action != PubSubMessageAction.DELETE:
            _LOGGER.exception(f'Invalid action: {action} for this class')
            raise ValueError

        msg = PubSubDataDeleteMessage(data_dict)

        msg.data_class: SchemaDataItem = \
            schema.data_classes[data_dict['class_name']].referenced_class
        msg.class_name: str = msg.data_class.name

        # Data is the number of items of the class specified by data_class
        # were deleted
        msg.data = data_dict.get('data')

        return msg
