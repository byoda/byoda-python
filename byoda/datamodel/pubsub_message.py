'''
The generic PubSub classes from which tech-specific classes should
derive

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


from uuid import UUID
from typing import TypeVar
from logging import getLogger

import orjson

from byoda.datamodel.datafilter import DataFilterSet

from byoda.datatypes import IdType
from byoda.datatypes import PubSubMessageType
from byoda.datatypes import PubSubMessageAction

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)

SchemaDataItem = TypeVar('SchemaDataItem')
Schema = TypeVar('Schema')


class PubSubMessage():
    '''
    Generic class for PubSub messages
    '''

    __slots__ = [
        'action', 'class_name', 'data_class', 'node', 'type',
        'origin_id', 'origin_id_type', 'origin_class_name'
    ]

    def __init__(self, message_type: PubSubMessageType):
        self.type: PubSubMessageType = message_type

        # Used by PubSubDataMessage
        self.action: PubSubMessageAction | None = None
        self.class_name: str | None = None
        self.data_class: SchemaDataItem | None = None
        self.node: dict[str, object] | None = None

        self.origin_id: UUID | None = None
        self.origin_id_type: IdType | None = None
        self.origin_class_name: str | None = None

    def to_bytes(self) -> bytes:
        '''
        Classes derived from PubSubMessage should override this method
        '''

        raise NotImplementedError

    def to_dict(self):
        '''
        Classes derived from PubSubMessage should override this method
        '''

        data = {
            'type': self.type,
            'action': self.action,
            'class_name': self.class_name,
            'data_class': self.data_class,
            'node': self.node,
            'origin_id': self.origin_id,
            'origin_id_type': self.origin_id_type,
            'origin_class_name': self.origin_class_name,
        }

        if self.type and isinstance(self.type, PubSubMessageType):
            data['type'] = self.type.value

        if self.action and isinstance(self.action, PubSubMessageAction):
            data['action'] = self.action.value

        if self.data_class and isinstance(self.data_class, SchemaDataItem):
            data['data_class'] = self.data_class.class_name

        return data

    @staticmethod
    def parse(message: bytes, schema: Schema = None):
        '''
        Factory parser for messages of all classes derived from PubSubMessage

        :param message: the message received by PubSub.recv()
        :param schema: the schema for the service for which the message was
        received

        '''

        all_data = orjson.loads(message)

        msg_type: str = all_data['type'].lower()
        action: str = all_data['action'].lower()

        _LOGGER.debug(
            f'Parsing message with type {msg_type} and action {action}'
        )
        if msg_type == PubSubMessageType.DATA.value:
            if action == PubSubMessageAction.APPEND.value:
                msg = PubSubDataAppendMessage.parse(all_data, schema)
            elif action == PubSubMessageAction.DELETE.value:
                msg = PubSubDataDeleteMessage.parse(all_data, schema)
            elif action == PubSubMessageAction.MUTATE.value:
                msg = PubSubDataMutateMessage.parse(all_data, schema)
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
                 data_class: SchemaDataItem | None = None):
        '''
        Constructor for Data messages.

        :param action:
        :param data: the metadata and payload data for the message
        '''

        if not data:
            raise ValueError(
                f'Data cannot be empty for action {action} '
                f'for class {data_class.name}'
            )

        super().__init__(PubSubMessageType.DATA)

        self.action = action
        self.node: dict[str, object] = data.get('node')
        self.data_class: SchemaDataItem = data_class

        self.class_name: str | None = None
        if data_class:
            self.class_name = data_class.name

        self.origin_id: UUID | None = data.get('origin_id')
        if self.origin_id and isinstance(self.origin_id, str):
            self.origin_id = UUID(self.origin_id)

        self.origin_id_type: IdType | None = data.get('origin_id_type')
        if self.origin_id_type and isinstance(self.origin_id_type, str):
            self.origin_id_type = IdType(self.origin_id_type)

        self.origin_class_name: str | None = data.get('origin_class_name')

        self.filter: str | None = data.get('filter')

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
               data_class: SchemaDataItem,
               origin_id: UUID | None = None,
               origin_id_type: IdType | None = None,
               origin_class_name: str | None = None):
        '''
        Factory for creating a PubSubDataMessage

        :param action: the action to perform
        :param data: the payload data (so not including metadata) to send
        :param data_class: the data class that the data originated from
        :param origin_id:
        :param origin_id_type:
        :param origin_class_name:
        :returns: PubSubDataMessage
        '''

        msg = PubSubDataMessage(
            action, origin_id=origin_id, origin_id_type=origin_id_type,
            origin_class_name=origin_class_name
        )
        msg.data_class: SchemaDataItem = data_class
        msg.class_name: str = data_class.name
        msg.node: dict[str, object] = data

        return msg

    def to_bytes(self):
        '''
        Serializes the message to a list of bytes
        '''

        data: dict[str, object] = {
            'type': self.type,
            'action': self.action,
            'class_name': self.class_name,
            'node': self.node,
            'origin_id': self.origin_id,
            'origin_id_type': self.origin_id_type,
            'origin_class_name': self.origin_class_name,
            'filter': self.filter,
        }
        return orjson.dumps(data)


class PubSubDataAppendMessage(PubSubDataMessage):
    def __init__(self, data: dict[str, object],
                 data_class: SchemaDataItem | None = None):
        '''
        Constructor for Data Append messages.

        :param data: the metadata and payload data for the message
        :param data_class: the data class that the data comes from
        :returns: PubSubDataAppendMessage
        :raises:
        '''

        super().__init__(PubSubMessageAction.APPEND, data, data_class)

    @staticmethod
    def create(data: object, data_class: SchemaDataItem,
               origin_id: UUID | None = None,
               origin_id_type: IdType | None = None,
               origin_class_name: str | None = None):
        '''
        Factory for creating a PubSubDataAppendMessage

        :param data: the payload data (so not including metadata) to send
        :param data_class: the data class that the data originated from
        :param origin_id:
        :param origin_id_type:
        :param origin_class_name:
        :returns: PubSubDataAppendMessage
        :raises:
        '''

        all_data: dict[str, object] = {
            'node': data,
            'origin_id': origin_id,
            'origin_id_type': origin_id_type,
            'origin_class_name': origin_class_name,
            'hops': 0,
        }
        msg = PubSubDataAppendMessage(all_data, data_class)

        return msg

    @staticmethod
    def parse(data: bytes | dict, schema: Schema):
        '''
        Factory, parses an Data Append message received over pub/sub

        :param data: the message received, including meta- and payload data
        :param schema: the schema for the service for which the message
        was received
        :returns: PubSubDataAppendMessage
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
            schema.data_classes[data_dict['class_name']]
        msg.class_name: str = msg.data_class.name

        referenced_class: SchemaDataItem = msg.data_class.referenced_class
        msg.node: dict[str, object] = referenced_class.normalize(
            data_dict.get('node')
        )

        return msg


class PubSubDataMutateMessage(PubSubDataMessage):
    def __init__(self, data: int, data_class: SchemaDataItem = None):
        '''
        Constructor

        Constructor for Data Mutate messages.

        :param data: the metadata and payload data for the message
        :param data_class: the data class that the data comes from
        :returns: self
        :raises:
        '''

        super().__init__(PubSubMessageAction.MUTATE, data, data_class)

    @staticmethod
    def create(data: int, data_class: SchemaDataItem,
               data_filter_set: DataFilterSet,
               origin_id: UUID | None = None,
               origin_id_type: IdType | None = None,
               origin_class_name: str | None = None):
        '''
        Factory for creating a PubSubDataMutateMessage

        :param data: the payload data (so not including metadata) to send
        :param data_class: the data class that the data originated from
        :param origin_id:
        :param origin_id_type:
        :param origin_class_name:
        :returns: PubSubDataMutateMessage
        :raises:
        '''

        all_data: dict[str, object] = {
            'data': data,
            'origin_id': origin_id,
            'origin_id_type': origin_id_type,
            'origin_class_name': origin_class_name,
            'filter': str(data_filter_set),
        }

        msg = PubSubDataMutateMessage(all_data, data_class)

        return msg

    @staticmethod
    def parse(data: bytes | dict, schema: Schema):
        '''
        Factory, parses a message received over pub/sub. Normalizes
        received data to the data class specified in the message

        :param data: the number of deleted items
        :param schema: the schema for the service for which the message
        was received
        :returns: PubSubDataMutateMessage
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
        if action != PubSubMessageAction.MUTATE:
            _LOGGER.exception(f'Invalid action: {action} for this class')
            raise ValueError

        msg = PubSubDataMutateMessage(data_dict)

        class_name: str = data_dict['class_name']
        msg.data_class: SchemaDataItem = \
            schema.data_classes[class_name].referenced_class

        msg.class_name: str = msg.data_class.name

        return msg


class PubSubDataDeleteMessage(PubSubDataMessage):
    def __init__(self, data: int, data_class: SchemaDataItem = None):
        '''
        Constructor for Data Delete messages.

        :param data: the metadata and payload data for the message
        :param data_class: the data class that the data comes from
        :returns: self
        :raises:
        '''

        super().__init__(PubSubMessageAction.DELETE, data, data_class)

    @staticmethod
    def create(data_class: SchemaDataItem, data_filter_set: DataFilterSet):
        '''
        Factory for creating a PubSubDataDeleteMessage

        :param data_class: the data class that the data originated from
        :param data_filter: the filter specifying the data to delete
        :returns: PubSubDataMutateMessage
        :raises:
        '''

        all_data: dict[str, str] = {
            'data': None,
            'filter': str(data_filter_set)
        }

        msg = PubSubDataDeleteMessage(all_data, data_class)

        return msg

    @staticmethod
    def parse(data: bytes | dict, schema: Schema):
        '''
        Factory, parses a message received over pub/sub. Normalizes
        received data to the data class specified in the message

        :param data: the number of deleted items
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
            schema.data_classes[data_dict['class_name']]
        msg.class_name: str = msg.data_class.name

        # Data is the number of items of the class specified by data_class
        # were deleted
        msg.data = data_dict.get('data')

        return msg
