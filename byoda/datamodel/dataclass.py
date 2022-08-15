'''
Class for data classes defined in the JSON Schema used
for generating the GraphQL Strawberry code based on Jinja2
templates


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from enum import Enum
from copy import copy
from uuid import UUID
from urllib.parse import urlparse, ParseResult
from datetime import datetime
from typing import TypeVar


from byoda.datatypes import RightsEntityType
from byoda.datatypes import DataOperationType
from byoda.datatypes import IdType
from byoda.datatypes import DataType

from .dataaccessright import DataAccessRight

from byoda import config

_LOGGER = logging.getLogger(__name__)

RequestAuth = TypeVar('RequestAuth')
Member = TypeVar('Member')


# We create a number of standard APIs for each class to manipulate data.
class GraphQlAPI(Enum):
    # flake8: noqa=E221
    MUTATE    = 'mutate'
    APPEND    = 'append'
    SEARCH    = 'search'
    DELETE    = 'delete'


# Translation from jsondata data type to Python data type in the Jinja template
PYTHON_SCALAR_TYPE_MAP = {
    DataType.STRING: 'str',
    DataType.INTEGER: 'int',
    DataType.NUMBER: 'float',
    DataType.BOOLEAN: 'bool',
    DataType.DATETIME: 'datetime',
    DataType.UUID: 'UUID',
}

GRAPHQL_SCALAR_TYPE_MAP = {
    DataType.STRING: 'String',
    DataType.INTEGER: 'Int',
    DataType.NUMBER: 'Float',
    DataType.BOOLEAN: 'Boolean',
    DataType.DATETIME: 'DateTime',
    DataType.UUID: 'UUID',
}

class SchemaDataItem:
    '''
    Class used to model the 'data classes' defined in the JSON Schema.
    The class is used in the Jinja2 templates to generate python3
    code leveraging the Strawberry GraphQL module.

    A data 'class' here can be eiter an object/dict, array/list or scalar
    '''

    def __init__(self, class_name: str, schema: dict, schema_id: str) -> None:

        self.name: str | None = class_name
        self.schema: dict = schema
        self.description: str = schema.get('description')
        self.item_id: str = schema.get('$id')
        self.schema_id: str = schema_id
        self.schema_url: ParseResult = urlparse(schema_id)
        self.enabled_apis: set = set()

        self.type: DataType = DataType(schema['type'])

        # Used by SchemaDataArray to point to the class the entries
        # of the array have
        self.referenced_class: str = None

        self.python_type, self.graphql_type = self.get_types(
            class_name, self.schema
        )

        self.access_controls: list[DataAccessRight] = {}

        self.parse_access_controls()

    def get_types(self, data_name: str, data_schema: dict
                       ) -> tuple[str, str]:
        '''
        Returns translation of the jsonschema -> python typing string
        and of the jsonschema -> graphql typing string

        :param name: name of the data element
        :param subschema: json-schema blurb for the data element
        :returns: the Python typing value and the GraphQL typing value for
        the data element
        :raises: ValueError, KeyError
        '''

        js_type = data_schema.get('type')
        if not js_type:
            raise ValueError(f'Class {data_name} does not have a type defined')

        try:
            jsonschema_type = DataType(js_type)
        except KeyError:
            raise ValueError(
                f'Data class {data_name} is of unrecognized'
                f'data type: {jsonschema_type}'
            )

        if jsonschema_type not in (DataType.OBJECT, DataType.ARRAY):
            try:
                format = data_schema.get('format')
                if format and format.lower() in ('date-time', 'uuid'):
                    format_datatype = DataType(format)
                    python_type: str = PYTHON_SCALAR_TYPE_MAP[format_datatype]
                    graphql_type: str = GRAPHQL_SCALAR_TYPE_MAP[format_datatype]
                else:
                    python_type: str = PYTHON_SCALAR_TYPE_MAP[jsonschema_type]
                    graphql_type: str = GRAPHQL_SCALAR_TYPE_MAP[jsonschema_type]
            except KeyError:
                raise ValueError(
                    f'No GraphQL data type mapping for {jsonschema_type}'
                )

            return python_type, graphql_type
        elif jsonschema_type == DataType.ARRAY:
            items = data_schema.get('items')
            if not items:
                raise ValueError(
                    f'Array {data_name} does not have items defined'
                )

            if 'type' in items:
                python_type = f'List[{PYTHON_SCALAR_TYPE_MAP[DataType(items["type"])]}]'
                graphql_type = f'[{GRAPHQL_SCALAR_TYPE_MAP[DataType(items["type"])]}!]'
                return python_type, graphql_type
            elif '$ref' in items:
                if not items['$ref'].startswith('https') and items['$ref'].count('/') != 2:
                    raise ValueError(
                        f'Reference for {data_name} must follow format '
                        f' of "/schema/{data_name}"'
                    )
                class_reference = items['$ref'].split('/')[-1]
                python_type = f'List[{class_reference}]'
                graphql_type = f'[{class_reference}!]'
                return python_type, graphql_type
        elif jsonschema_type == DataType.OBJECT:
            return None, None

        raise ValueError(
            f'Unknown data type for {data_name}: {jsonschema_type}'
        )

    @staticmethod
    def create(class_name: str, schema: dict, schema_id: str,
               classes: dict = None):
        '''
        Factory for instances of classes derived from SchemaDataItem
        '''

        item_type = schema.get('type')
        if not item_type:
            raise ValueError(f'No type found in {class_name}')

        if item_type == 'object':
            item = SchemaDataObject(class_name, schema, schema_id)
        elif item_type == 'array':
            item = SchemaDataArray(
                class_name, schema, schema_id, classes=classes
            )
        else:
            item = SchemaDataScalar(class_name, schema, schema_id)

        return item

    def normalize(self, value: str | int | float) -> str | int | float:
        '''
        Normalizes the value to the correct data type for the item
        '''

        return value

    def parse_access_controls(self) -> None:
        '''
        Parse the #accesscontrol key of the data item in the JSON Schema
        '''

        rights = self.schema.get('#accesscontrol')
        if not rights:
            return

        if not isinstance(rights, dict):
            raise ValueError(
                f'Access controls must be an object for class {self.name}'
            )

        self.access_rights: dict[RightsEntityType, list[DataAccessRight]] = {}

        for entity_type_data, access_rights_data in rights.items():
            access_rights = DataAccessRight.get_access_rights(
                entity_type_data, access_rights_data
            )
            self.access_controls[entity_type] = access_rights

            permitted_actions = [
                 access_right.data_operation_type
                 for access_right in access_rights
            ]

            for action in permitted_actions:
                if action.data_operation_type in (
                        DataOperationType.CREATE,
                        DataOperationType.UPDATE):
                    self.enabled_apis.add(GraphQlAPI.MUTATE)
                if action.data_operation_type == DataOperationType.APPEND:
                    self.enabled_apis.add(GraphQlAPI.APPEND)
                if action.data_operation_type == DataOperationType.DELETE:
                    self.enabled_apis.add(GraphQlAPI.DELETE)
                if action.data_operation_type == DataOperationType.SEARCH:
                    self.enabled_apis.add(GraphQlAPI.SEARCH)

    async def authorize_access(self, operation: DataOperationType,
                               auth: RequestAuth, service_id: int):
        '''
        Checks whether the entity performing the request has access for
        the requested operation to the data item

        :param operation: requested operation
        :param auth: the authenticated requesting entity
        :param service_id: service_id for membership that received the request
        :returns: None if no determination was made, otherwise True or False
        '''

        _LOGGER.debug(f'Checking authorization for operation {operation}')
        if service_id != auth.service_id:
            _LOGGER.debug(
                f'GraphQL API for service ID {service_id} called with credentials '
                f'for service: {auth.service_id}'
            )
            return False

        if not self.access_controls:
            # No access rights for the data element so can't decide
            # whether access is allowed or not
            _LOGGER.debug(
                f'No access controls defined for data item {self.name}'
            )
            return None

        for entity, access_right in self.access_controls.items():
            permitted_actions = [
                access_right
            ]
            # Let's find the access rights that apply to the requestor
            # Anyone is allowed to
            if entity == RightsEntityType.ANONYMOUS:
                if operation in access_right.permitted_actions:
                    _LOGGER.debug(
                        f'Authorizing anonymous access for data item {self.name}'
                    )
                    return True

            # Are we querying the GraphQL API ourselves?
            if entity == RightsEntityType.MEMBER:
                if auth.id_type == IdType.MEMBER:
                    if authorize_member(service_id, auth):
                        if operation in permissions.permitted_actions:
                            _LOGGER.debug(
                                'Authorizing member access for data '
                                f'item {self.name}'
                            )
                            return True

            # Did the service server call our GraphQL API?
            if entity == RightsEntityType.SERVICE:
                if auth.id_type == IdType.SERVICE:
                    if authorize_service(service_id, auth):
                        if operation in permissions.permitted_actions:
                            _LOGGER.debug(
                                'Authorizing service access for data item '
                                f'{self.name}')
                            return True

            if entity == RightsEntityType.ANY_MEMBER:
                if auth.id_type == IdType.MEMBER:
                    if authorize_any_member(service_id, auth):
                        if operation in permissions.permitted_actions:
                            _LOGGER.debug(
                                'Authorizing any member access for data item '
                                f'{self.name}'
                            )
                            return True

            if entity == RightsEntityType.NETWORK:
                if await authorize_network(
                        service_id, permissions.relations,
                        permissions.distance, auth):
                    if operation in permissions.permitted_actions:

                        return True

        _LOGGER.debug(f'No access controls matched for data item {self.name}')

        return None

class SchemaDataScalar(SchemaDataItem):
    def __init__(self, class_name: str, schema: dict, schema_id: str) -> None:
        super().__init__(class_name, schema, schema_id)

        if self.type == DataType.STRING:
            self.format: str = self.schema.get('format')
            if self.format == 'date-time':
                self.type = DataType.DATETIME
                self.python_type = 'datetime'
            elif (self.format == 'uuid' or self.schema.get('regex') ==
                    (
                        '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}'
                        '-[0-9a-f]{12}$'
                    )):
                self.type = DataType.UUID
                self.python_type = 'UUID'

    def normalize(self, value: str | int | float) -> str | int | float:
        '''
        Normalizes the value to the correct data type for the item
        '''

        if (self.type == DataType.UUID
                and value and not isinstance(value, UUID)):
            result = UUID(value)
        elif (self.type == DataType.DATETIME
                and value and not isinstance(value, datetime)):
            result = datetime.fromisoformat(value)
        else:
            result = value

        return result

class SchemaDataObject(SchemaDataItem):
    def __init__(self, class_name: str, schema: dict, schema_id: str) -> None:
        super().__init__(class_name, schema, schema_id)

        # 'Defined' classes are objects under the '$defs' object
        # of the JSON Schema. We don't create GraphQL mutations for
        # named classes. We require all these 'defined' classes to
        # be defined locally in the schema and their id
        # thus starts with '/schemas/' instead of 'https://'. Furthermore,
        # we require that there no further '/'s in the id

        self.fields: dict[str:SchemaDataItem] = {}
        self.required_fields: list[str] = schema.get('required')
        self.defined_class: bool = False

        if self.item_id:
            self.defined_class = True

        for field, field_properties in schema['properties'].items():
            if field_properties['type'] == 'object':
                raise ValueError(
                    f'Nested objects or arrays under object {class_name} are '
                    'not yet supported'
                )
            elif field_properties['type'] == 'array':
                items = field_properties.get('items')
                if not items:
                    raise ValueError(
                        f'Array for {class_name} does not specify items'
                    )
                if not isinstance(items, dict):
                    raise ValueError(
                        f'Items property of array {class_name} must be an '
                        'object'
                    )

            item = SchemaDataItem.create(field, field_properties, schema_id)

            self.fields[field] = item

    def normalize(self, value: dict) -> dict:
        '''
        Normalizes the values in a dict
        '''

        data = copy(value)
        for field in data:
            if field == 'remote_member_id':
                if isinstance(data[field], str):
                    # special handling for 'remote_member_id', which is a
                    # parameter used for remote appends
                    data[field] = UUID(data[field])
            elif field != 'depth':
                data_class = self.fields[field]
                data[field] = data_class.normalize(value[field])

        return data

    async def authorize_access(self, operation: DataOperationType,
                               auth: RequestAuth, service_id: int) -> bool:
        '''
        Checks whether the entity performing the request has access for the
        requested operation to the data item

        :param operation: requested operation
        :param auth: the authenticated requesting entity
        :returns: None if no determination was made, otherwise True or False
        '''

        access_allowed: bool | None = await super().authorize_access(
            operation, auth, service_id
        )

        if access_allowed is False:
            return False

        for data_class in self.fields.values():
            child_access_allowed = await data_class.authorize_access(
                operation, auth, service_id
            )
            _LOGGER.debug(
                f'Object child data access authorized: {child_access_allowed}'
            )

            if child_access_allowed is False:
                return False

        _LOGGER.debug(
            f'Object data access authorized: {access_allowed} for data '
            f'item {self.name}'
        )
        return access_allowed


class SchemaDataArray(SchemaDataItem):
    def __init__(self, class_name: str, schema: dict, schema_id: str,
                 classes: dict) -> None:
        super().__init__(class_name, schema, schema_id)

        items = schema.get('items')
        if not items:
            raise ValueError(
                'Schema properties for array {class_name} does not have items '
                'defined'
            )
        if 'type' in items:
            self.items = DataType(items['type'])
            self.referenced_class = SchemaDataItem.create(None, schema['items'], self.schema_id)
        elif '$ref' in items:
            self.items = DataType.REFERENCE
            reference = items['$ref']
            url = urlparse(reference)
            if not url.path.startswith('/schemas/'):
                raise ValueError(
                    f'Data reference {reference} must start with "/schemas/"'
                )
            if url.path.count('/') > 2:
                raise ValueError(
                    f'Data reference {reference} must have path with no more '
                    'than 2 "/"s'
                )

            referenced_class = reference.split('/')[-1]
            if referenced_class not in classes:
                raise ValueError(
                    f'Unknown class {referenced_class} referenced by {class_name}'
                )
            self.referenced_class = classes[referenced_class]
        else:
            raise ValueError(
                f'Array {class_name} must have "type" or "$ref" defined'
            )

    def normalize(self, value: list) -> list:
        '''
        Normalizes the data structure in the array to the types defined in
        the service contract
        '''

        data = copy(value)

        result = []
        for item in data or []:
            if self.referenced_class:
                normalized_item = self.referenced_class.normalize(item)
            result.append(normalized_item)

        return result

    async def authorize_access(self, operation: DataOperationType,
                               auth: RequestAuth, service_id: int) -> bool:
        '''
        Checks whether the entity performing the request has access for the
        requested operation to the data item

        :param operation: requested operation
        :param auth: the authenticated requesting entity
        :returns: None if no determination was made, otherwise True or False
        '''

        access_allowed: bool | None = await super().authorize_access(
            operation, auth, service_id
        )

        if access_allowed is False:
            return False

        child_access_allowed = None
        if self.referenced_class:
            child_access_allowed = await self.referenced_class.authorize_access(
                operation, auth, service_id
            )
            _LOGGER.debug(
                f'Child of array data access authorized: '
                f'{child_access_allowed} for data item {self.name}'
            )
            if child_access_allowed is False:
                return False

        _LOGGER.debug(
            f'Array data access authorized: {access_allowed} for data '
            f'item {self.name}'
        )

        return access_allowed


def authorize_any_member(service_id: int, auth: RequestAuth) -> bool:
    '''
    Authorizes any member of the service, regardless of whether the client
    is in our network

    :param service_id: service membership that received the GraphQL API request
    :param auth: the object with info about the authentication of the client
    :returns: whether the client is authorized to perform the requested
    operation
    '''

    member = config.server.account.memberships.get(service_id)

    if member and auth.member_id and auth.service_id == service_id:
        _LOGGER.debug(f'Authorization success for any member {auth.member_id}')
        return True

    _LOGGER.debug(f'Authorization rejected for any member {auth.member_id}')
    return False


def authorize_service(service_id: int, auth: RequestAuth) -> bool:
    '''
    Authorizes requests made with the TLS cert of the service

    :param service_id: service membership that received the GraphQL API request
    :param auth: the object with info about the authentication of the client
    :returns: whether the client is authorized to perform the requested
    operation
    '''

    member = config.server.account.memberships.get(service_id)

    if (member and auth.service_id is not None
            and auth.service_id == service_id):
        _LOGGER.debug(f'Authorization success for service {service_id}')
        return True

    _LOGGER.debug('Authorization rejected for service {service_id}')
    return False


