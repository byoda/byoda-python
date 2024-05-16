'''
Class for data classes defined in the JSON Schema used
for generating the Data API code based on Jinja2
templates


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

# flake8: noqa: E221

import orjson
import jinja2

from enum import Enum
from copy import copy
from uuid import UUID
from typing import Self
from hashlib import sha256
from typing import TypeVar

from datetime import datetime
from datetime import timezone
from logging import getLogger

from urllib.parse import urlparse
from urllib.parse import ParseResult

from byoda.datatypes import RightsEntityType
from byoda.datatypes import DataOperationType
from byoda.datatypes import DataType
from byoda.datatypes import MARKER_ACCESS_CONTROL
from byoda.storage.pubsub import PubSub

from byoda.util.logger import Logger

from byoda import config

from byoda.exceptions import ByodaDataClassReferenceNotFound

from .dataaccessright import DataAccessRight

_LOGGER: Logger = getLogger(__name__)

RequestAuth = TypeVar('RequestAuth')
Member = TypeVar('Member')
Schema = TypeVar('Schema')


class DataProperty(Enum):
    # flask8: noqa=E221
    PRIMARY_KEY = 'primary_key'
    COUNTER     = 'counter'
    INDEX       = 'index'
    CACHE_ONLY  = 'cache_only'

# Translation from jsondata data type to Python data type in the Jinja template
PYTHON_SCALAR_TYPE_MAP: dict[DataType, str] = {
    DataType.STRING: 'str',
    DataType.INTEGER: 'int',
    DataType.NUMBER: 'float',
    DataType.BOOLEAN: 'bool',
    DataType.DATETIME: 'datetime',
    DataType.UUID: 'UUID',
}

MARKER_PROPERTIES: str = '#properties'

SECONDS_PER_UNIT: dict[str, int] = {
    's': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800
}


class SchemaDataItem:
    '''
    Class used to model the 'data classes' defined in the JSON Schema.
    The class is used in the Jinja2 templates to generate python3
    code leveraging the Data API module.

    A data 'class' here can be eiter an object/dict, array/list or scalar
    '''

    __slots__: list[str] = [
        'name', 'schema_data', 'description', 'item_id', 'schema_id',
        'service_id', 'schema_url', 'defined_class',
        'fields', 'properties', 'is_index', 'is_counter', 'type',
        'referenced_class', 'referenced_class_field', 'primary_key',
        'is_primary_key', 'required', 'python_type',
        'storage_name', 'storage_type', 'pubsub_class', 'access_rights',
        'child_has_accessrights', 'cache_only', 'expires_after', 'version',
        'is_scalar'
    ]

    def __init__(self, class_name: str, schema_data: dict[str:object],
                 schema: Schema) -> None:
        '''
        Constructor

        :param class_name: name of the class
        :param schema: Schema instance
        :param schema_data: json-schema blurb for the class
        '''

        self.name: str | None = class_name
        self.schema_data: dict[str, object] = schema_data
        self.description: str | None = schema_data.get('description')
        self.item_id: str | None = schema_data.get('$id')
        self.schema_id: str = schema.schema_id
        self.service_id: int = schema.service_id
        self.version: int = schema.version
        self.schema_url: ParseResult = urlparse(schema.schema_id)

        # Is this a class referenced by other classes
        self.defined_class: bool | None = None

        # Is this a simple data type, ie. not an object or array?
        self.is_scalar: bool = True

        self.fields: list[SchemaDataItem] | None = None

        self.properties: set(DataProperty) = set()

        # Should data for this class automatically expire and be purged?
        self.cache_only: bool = False

        # Time in seconds when data for this class should be purged
        self.expires_after: int | None = None

        # Properties for the class
        value: int | None = None
        for property in schema_data.get(MARKER_PROPERTIES, []):
            if isinstance(property, list):
                # Property looks like ['cache_only', '1w']
                property, value = property
            elif ':' in property:
                # Property looks like 'cache_only:1w'
                property, value = property.split(':', 2)

            property_instance = DataProperty(property)
            self.properties.add(property_instance)

            if property_instance == DataProperty.CACHE_ONLY:
                self.expires_after: int = self._convert_timespec_to_seconds(
                    value
                )

        # Create index on this item in an array of SchemaDataObject
        self.is_index: bool = DataProperty.INDEX in self.properties

        # Keep counter per unique value of the item in an SchemaDataArray
        # Setting this will also cause the item to be indexed
        self.is_counter: bool = DataProperty.COUNTER in self.properties

        # Cache-only is used for data for data classes that should
        # not be persisted but cached instead. Typically, this is
        # data downloaded from another pod and cached in our own pod
        self.cache_only: bool = DataProperty.CACHE_ONLY in self.properties

        self.type: DataType = DataType(schema_data['type'])

        # Used by SchemaDataArray to point to the class the entries
        # of the array have
        self.referenced_class: str = None

        # Used by SchemaDataArray so it knows which field to match
        # with in 'join's of two tables
        self.referenced_class_field: str = None

        # Which field of an object to use for 'join's of two tables
        self.primary_key: str = None

        # Is this the field that should be used to match for 'joins'
        # with other tables?
        self.is_primary_key: bool = DataProperty.PRIMARY_KEY in self.properties

        # Used for fields of a SchemaDataObject listed as 'required'. All
        # fields with property primary_key are also required
        self.required: bool = self.is_primary_key

        self.python_type: str = self.get_types(class_name, self.schema_data)

        # The class for storing data for the service sets the values
        # for storage_name and storage_type for child data items
        # under the root data item
        self.storage_name: str = None
        self.storage_type: str = None

        # The Pub/Sub for communicating changes to data using this class
        # instance. Only used for SchemaDataArray instances
        self.pubsub_class: PubSub | None = None

        self.access_rights: list[DataAccessRight] = {}

        # When authorizing requests, we don't have to review the access
        # rights of children when they don't have access rights defined.
        # TODO: Until this is implemented, we default to True
        self.child_has_accessrights: bool = True

        self.parse_access_controls()

    def get_types(self, data_name: str, schema_data: dict) -> str:
        '''
        Returns translation of the jsonschema -> python typing string

        :param name: name of the data element
        :param subschema: json-schema blurb for the data element
        :returns: the Python typing value for the data element
        :raises: ValueError, KeyError
        '''

        js_type: str | None = schema_data.get('type')
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
                format: str | None = schema_data.get('format')
                if format and format.lower() in ('date-time', 'uuid'):
                    format_datatype = DataType(format)
                    python_type: str = PYTHON_SCALAR_TYPE_MAP[format_datatype]
                else:
                    python_type: str = PYTHON_SCALAR_TYPE_MAP[jsonschema_type]
            except KeyError:
                raise ValueError(
                    f'No Python data type mapping for {jsonschema_type}'
                )

            return python_type
        elif jsonschema_type == DataType.ARRAY:
            items: dict | None = schema_data.get('items')
            if not items:
                raise ValueError(
                    f'Array {data_name} does not have items defined'
                )
            if not isinstance(items, dict):
                raise ValueError(
                    f'Items property of array {data_name} must be an object'
                )
            if 'type' in items:
                python_type = f'list[{PYTHON_SCALAR_TYPE_MAP[DataType(items["type"])]}]'
                return python_type
            elif '$ref' in items:
                if not items['$ref'].startswith('https') and items['$ref'].count('/') != 2:
                    raise ValueError(
                        f'Reference for {data_name} must follow format '
                        f' of "/schema/{data_name}"'
                    )
                class_reference = items['$ref'].split('/')[-1]
                python_type = f'list[{class_reference}]'
                return python_type
        elif jsonschema_type == DataType.OBJECT:
            return None, None

        raise ValueError(
            f'Unknown data type for {data_name}: {jsonschema_type}'
        )

    @staticmethod
    def create(class_name: str, schema_data: dict[str, any], schema: Schema,
               classes: dict = {}, with_pubsub: bool = True
               ) -> Self | None:
        '''
        Factory for instances of classes derived from SchemaDataItem

        :param class_name: name of the class
        :param schema_data: json-schema blurb for the class
        :param schema: Schema instance
        :param classes: dictionary of classes already created
        :param with_pubsub: whether to create a PubSub instance for the class
        :returns: SchemaDataItem instance or None, if the item is declared
        obsolete in the service schema
        '''

        item_type: str | None = schema_data.get('type')
        if not item_type:
            raise ValueError(f'No type found in {class_name}')

        _LOGGER.debug(
            f'Creating data class instance for {class_name} '
            f'for type {item_type}'
        )

        if item_type == 'object':
            item = SchemaDataObject(
                class_name, schema_data, schema, classes=classes
            )
        elif item_type == 'array':
            item = SchemaDataArray(
                class_name, schema_data, schema, classes=classes, with_pubsub=with_pubsub
            )
        else:
            if schema_data.get('#obsolete', False) == True:
                return

            item = SchemaDataScalar(class_name, schema_data, schema)

        return item

    def normalize(self, value: str | int | float) -> str | int | float:
        '''
        Normalizes the value to the correct data type for the item
        '''

        return value

    def get_pydantic_model(self, environment: jinja2.Environment) -> str:
        raise NotImplementedError


    @staticmethod
    def _parse_reference(uri: str) -> str:
        '''
        Parses, reviews and extracts the referenced class from the url
        '''

        # Remove leading '#' if present
        if uri.startswith('#/'):
            uri = uri[1:]

        url: ParseResult = urlparse(uri)
        if not url.path.startswith('/schemas/'):
            raise ValueError(
                f'Data reference {uri} must start with "/schemas/"'
            )
        if url.path.count('/') > 2:
            raise ValueError(
                f'Data reference {uri} must have path with no more '
                'than 2 "/"s'
            )

        referenced_class: str = uri.split('/')[-1]

        return referenced_class

    def parse_access_controls(self) -> None:
        '''
        Parse the #accesscontrol key of the data item in the JSON Schema
        '''

        _LOGGER.debug(f'Parsing access controls for {self.name}')

        rights: dict | None = self.schema_data.get(MARKER_ACCESS_CONTROL)
        if not rights:
            _LOGGER.debug(f'No access rights defined for {self.name}')
            return

        if not isinstance(rights, dict):
            raise ValueError(
                f'Access controls must be an object for class {self.name}'
            )

        self.access_rights: dict[RightsEntityType, list[DataAccessRight]] = {}

        for entity_type_data, access_rights_data in rights.items():
            entity_type: RightsEntityType
            access_rights: list[DataAccessRight]
            entity_type, access_rights = DataAccessRight.get_access_rights(
                entity_type_data, access_rights_data
            )
            self.access_rights[entity_type] = access_rights

    async def authorize_access(self, operation: DataOperationType,
                               auth: RequestAuth, service_id: int, depth: int
                               ) -> bool | None:
        '''
        Checks whether the entity performing the request has access for
        the requested operation to the data item

        :param operation: requested operation
        :param auth: the authenticated requesting entity
        :param service_id: service_id for membership that received the request
        :returns: None if no determination was made, otherwise True or False
        '''

        _LOGGER.debug(f'Checking authorization for operation {operation}')
        if auth.is_authenticated and service_id != auth.service_id:
            _LOGGER.debug(
                f'Data API for service ID {service_id} called with '
                f'credentials for service: {auth.service_id}'
            )
            return False

        if not self.access_rights:
            # No access rights for the data element so can't decide
            # whether access is allowed or not
            _LOGGER.debug(
                f'No access controls defined for data item {self.name}'
            )
            return None

        for access_rights in self.access_rights.values():
            for access_right in access_rights:
                result: bool | None = await access_right.authorize(
                    auth, service_id, operation, depth
                )
                if result:
                    return True

        _LOGGER.debug(f'No access controls matched for data item {self.name}')

        return None

    def _convert_timespec_to_seconds(self, time_spec: str = '1w') -> int:
        '''
        Converts a time specification to seconds
        '''

        seconds: int
        if time_spec is None:
            seconds = SECONDS_PER_UNIT['w']
        elif time_spec[-1] not in SECONDS_PER_UNIT:
            try:
                seconds = int(time_spec)
            except ValueError as exc:
                raise ValueError(
                    f'Invalid value for timespec: {time_spec}: {exc}'
                )
        else:
            seconds = int(time_spec[:-1]) * SECONDS_PER_UNIT[time_spec[-1]]

        return seconds


class SchemaDataScalar(SchemaDataItem):
    __slots__: list[str] = [
        'format', 'equal_operator'
    ]

    def __init__(self, class_name: str, schema_data: dict, schema: Schema) -> None:
        super().__init__(class_name, schema_data, schema)

        self.defined_class: bool = False
        self.format: str | None = None

        # equal_operator is used for converting data for data_class back to
        # a DataSetFilter that matches that data
        self.equal_operator: str = 'eq'


        if self.type == DataType.STRING:
            self.format: str = self.schema_data.get('format')
            if self.format == 'date-time':
                self.type = DataType.DATETIME
                self.python_type = 'datetime'
                self.equal_operator = 'at'
            elif (self.format == 'uuid' or self.schema_data.get('regex') ==
                    (
                        '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}'
                        '-[0-9a-f]{12}$'
                    )):
                self.type = DataType.UUID
                self.python_type = 'UUID'
                self.equal_operator = 'eq'

        if self.is_primary_key and self.type != DataType.UUID:
            raise ValueError(
                f'Primary key {self.name} must be of type UUID'
            )


        if (self.is_counter and not (
                self.type in (DataType.UUID, DataType.STRING, DataType.DATETIME,
                              DataType.INTEGER))):
            _LOGGER.exception(
                f'Only UUIDs, strings and datetimes can be counters: '
                f'{self.name}, {self.type}'
            )
            raise ValueError('Only UUIDs and strings can be counters')

        _LOGGER.debug(
            f'Created scalar class {self.name} of type {self.type} with '
            f'format {self.format} and python type {self.python_type}'
        )

    def normalize(self, value: str | int | float | datetime
                  ) -> str | int | float | UUID | datetime:
        '''
        Normalizes the value from the data store to the correct data type
        for the item in Python3
        '''

        result: datetime
        try:
            if (self.type == DataType.UUID
                    and value and not isinstance(value, UUID)):
                result = UUID(value)
            elif (self.type == DataType.DATETIME
                    and value and not isinstance(value, datetime)):
                if isinstance(value, str):
                    result = datetime.fromisoformat(value)
                else:
                    result = datetime.fromtimestamp(value, tz=timezone.utc)
            else:
                result = value
        except ValueError:
            raise ValueError(
                f'Value {value} for {self.name} is not of type {self.type}'
            )

        return result

class SchemaDataObject(SchemaDataItem):
    __slots__: list[str] = ['required_fields']

    def __init__(self, class_name: str, schema_data: dict, schema: Schema,
                 classes: dict[str, SchemaDataItem]) -> None:
        super().__init__(class_name, schema_data, schema)

        # 'Defined' classes are objects under the '$defs' object
        # of the JSON Schema. We don't create Data API mutation methods for
        # named classes. We require all these 'defined' classes to
        # be defined locally in the schema and their id
        # thus starts with '/schemas/' instead of 'https://'. Furthermore,
        # we require that there no further '/'s in the id

        self.fields: dict[str, SchemaDataItem] = {}
        self.required_fields: set[str] = schema_data.get('required', [])
        self.defined_class: bool = False
        self.is_scalar = False

        if DataProperty.COUNTER in self.properties:
            raise ValueError('Counters are not supported for objects')

        if DataProperty.INDEX in self.properties:
            raise ValueError('Index is not supported for objects')

        if DataProperty.PRIMARY_KEY in self.properties:
            raise ValueError('An object can not be a primary key')

        if self.item_id:
            self.defined_class = True

        for field, field_properties in schema_data['properties'].items():
            if 'type' not in field_properties:
                raise ValueError(
                    f'No type defined for field {field} of class {class_name}, '
                    f'which is a data class: {self.defined_class}'
                )
            if field_properties['type'] == 'object':
                raise ValueError(
                    f'Nested objects under object {class_name} are '
                    'not yet supported'
                )
            elif field_properties['type'] == 'array':
                items: dict[str, any] = field_properties.get('items')
                if not items:
                    raise ValueError(
                        f'Array for {class_name} does not specify items'
                    )
                if not isinstance(items, dict):
                    raise ValueError(
                        f'Items property of array {class_name} must be an '
                        'object'
                    )

            item: SchemaDataItem | None = SchemaDataItem.create(
                field, field_properties, schema, classes, with_pubsub=False
            )

            if item:
                self.fields[field] = item

                if item.is_primary_key:
                    self.primary_key = item.name

                if field in self.required_fields:
                    item.required = True

                _LOGGER.debug(f'Created object class {class_name}')

    def normalize(self, value: dict) -> dict[str, object]:
        '''
        Normalizes the values in a dict
        '''

        data: dict = copy(value)
        for field in data:
            data_class: SchemaDataItem | None = self.fields.get(field)
            if not data_class:
                # This can happen now that we store objects that have
                # an array of other objects as JSON strings
                _LOGGER.debug(f'Skipping unknown field {field}')
                continue

            data[field] = data_class.normalize(value[field])

        return data

    def get_cursor_hash(self, data: dict, origin_id: UUID | str | None) -> str:
        '''
        Helper function to generate cursors for objects based on the
        stringified values of the required fields of object

        :param data: the data to generate the cursor for
        :param origin_id: the origin ID to include in the cursor
        :returns: the cursor
        '''

        hash_gen: bytes = sha256()
        for field_name in self.required_fields:
            value: bytes = str(data.get(field_name, '')).encode('utf-8')
            hash_gen.update(value)

        if origin_id:
            hash_gen.update(str(origin_id).encode('utf-8'))

        cursor: str = hash_gen.hexdigest()

        return cursor[0:8]

    async def authorize_access(self, operation: DataOperationType,
                               auth: RequestAuth, service_id: int, depth: int
                               ) -> bool | None:
        '''
        Checks whether the entity performing the request has access for the
        requested operation to the data item

        :param operation: requested operation
        :param auth: the authenticated requesting entity
        :returns: None if no determination was made, otherwise True or False
        '''

        access_allowed: bool | None = await super().authorize_access(
            operation, auth, service_id, depth
        )

        if access_allowed is False:
            return False

        for data_class in self.fields.values():
            child_access_allowed = await data_class.authorize_access(
                operation, auth, service_id, depth
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

    def get_pydantic_data_model(self, environment: jinja2.Environment) -> str:
        '''
        Renders a Jinja2 template to generate a class deriving
        from the Pydantic v2 BaseModel
        '''

        template = environment.get_template('pydantic-model-object.py.jinja')

        code: str = template.render(data_class=self)

        return code

    def get_pydantic_request_model(self, environment: jinja2.Environment) -> str:
        '''
        Renders a Jinja2 template to generate a class deriving
        from the Pydantic v2 BaseModel for query, append, mutate, update or
        delete
        '''

        template_name = f'pydantic-model-rest-apis.py.jinja'
        template = environment.get_template(template_name)

        code: str = template.render(data_class=self)

        return code

class SchemaDataArray(SchemaDataItem):
    __slots__: list[str] = ['items']

    def __init__(self, class_name: str, schema_data: dict, schema: Schema,
                 classes: dict[str, SchemaDataItem], with_pubsub: bool =True
                 ) -> None:
        '''
        Constructor

        :param class_name: name of the class
        :param schema_data: json-schema blurb for the class
        :param schema: Schema instance
        :param classes: dictionary of classes already created
        :param pubsib: whether to create a PubSub instance for the class
        '''

        super().__init__(class_name, schema_data, schema)

        self.defined_class: bool = False
        self.is_scalar = False

        if DataProperty.COUNTER in self.properties:
            raise ValueError('Counters are not supported for arrays')

        if DataProperty.INDEX in self.properties:
            raise ValueError('Index is not supported for arraus')

        items: dict | None = schema_data.get('items')
        if not items:
            raise ValueError(
                'Schema properties for array {class_name} does not have items '
                'defined'
            )

        if not isinstance(items, dict):
            raise ValueError(
                f'items property for array {class_name} must be an object'
            )

        if 'type' in items:
            # This is an array of scalars or objects
            self.items = DataType(items['type'])
            self.referenced_class = SchemaDataItem.create(
                None, schema_data['items'], schema, classes, with_pubsub=False
            )
        elif '$ref' in items:
            # This is an array of objects of the referenced class
            self.items = DataType.REFERENCE
            referenced_class = SchemaDataArray._parse_reference(items['$ref'])
            if referenced_class not in classes or []:
                raise ByodaDataClassReferenceNotFound(
                    f'Unknown class {referenced_class} referenced by {class_name}'
                )

            self.referenced_class = classes[referenced_class]

            # The Pub/Sub for communicating changes to data using this class
            # instance. We only track changes for arrays at the top-level
            # of the schema
            if with_pubsub and config.test_case != "TEST_CLIENT":
                self.pubsub_class = PubSub.setup(
                    self.name, self, schema, is_sender=True
                )
        else:
            raise ValueError(
                f'Array {class_name} must have "type" or "$ref" defined'
            )

        _LOGGER.debug(
            f'Created array class {class_name} with referenced class '
            f'{self.referenced_class.name}'
        )

    def normalize(self, value: str | bytes) -> list:
        '''
        Normalizes the data structure in the array to the types defined in
        the service contract
        '''

        if not self.referenced_class:
            raise ValueError(
                f'Class {self.name} does not reference a class'
            )

        if type(value) in (str, bytes) and value:
            items = orjson.loads(value)
        else:
            items = value or []

        result: dict[str, bytes | int | float | UUID | bool] = []
        for item in items:
            normalized_item = self.referenced_class.normalize(item)
            result.append(normalized_item)

        return result

    def get_cursor_hash(self, data: dict[str, object], origin_member_id: UUID
                        ) -> str:
        '''
        Creates a hash of the required fields in the data that. This cursor
        is used for pagination of data in the array

        :param data: the data to create the cursor for
        :param origin_member_id: the member ID of the member that stores the
        data
        :returns: the cursor hash
        :raises: ValueError
        '''

        if not self.referenced_class:
            raise ValueError('This class does not reference objects')

        return self.referenced_class.get_cursor_hash(data, origin_member_id)

    async def authorize_access(self, operation: DataOperationType,
                               auth: RequestAuth, service_id: int, depth: int
                               ) -> bool | None:
        '''
        Checks whether the entity performing the request has access for the
        requested operation to the data item

        :param operation: requested operation
        :param auth: the authenticated requesting entity
        :param service_id: the service ID of the service specified in the
        request
        :param depth: the level of recurssion specified in the request
        :returns: None if no determination was made, otherwise True or False
        '''

        access_allowed: bool | None = await super().authorize_access(
            operation, auth, service_id, depth
        )

        if access_allowed is False:
            _LOGGER.debug(
                f'Access is not authorized for {operation} for service {service_id}'
            )
            return False

        child_access_allowed = None
        if self.referenced_class:
            child_access_allowed: bool | None = await self.referenced_class.authorize_access(
                operation, auth, service_id, depth
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

    def get_pydantic_data_model(self, environment: jinja2.Environment) -> str:
        '''
        Renders a Jinja2 template to generate a class deriving
        from the Pydantic v2 BaseModel
        '''

        template: jinja2.Template = environment.get_template(
            'pydantic-model-array.py.jinja'
        )

        code: str = template.render(data_class=self)

        return code

    def get_pydantic_request_model(self, environment: jinja2.Environment) -> str:
        '''
        Renders a Jinja2 template to generate a class deriving
        from the Pydantic v2 BaseModel for query, append, mutate, update or
        delete
        '''

        template_name: str = 'pydantic-model-rest-apis.py.jinja'
        template: jinja2.Template = environment.get_template(template_name)

        code: str = template.render(data_class=self)

        return code