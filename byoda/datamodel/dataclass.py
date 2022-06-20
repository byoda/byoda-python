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
from typing import Dict, List, Set
from urllib.parse import urlparse

from byoda.datatypes import RightsEntityType
from byoda.datatypes import DataOperationType

_LOGGER = logging.getLogger(__name__)


class DataType(Enum):
    # flake8: noqa=E221
    STRING    = 'string'
    INTEGER   = 'integer'
    NUMBER    = 'number'
    BOOLEAN   = 'boolean'
    OBJECT    = 'object'
    ARRAY     = 'array'
    REFERENCE = 'reference'

# We create a number of standard APIs for each class to manipulate data.
class GraphQlAPI(Enum):
    MUTATE    = 'mutate'
    APPEND    = 'append'
    SEARCH    = 'search'
    DELETE    = 'delete'


# Translation from jsondata data type to Python data type in the Jinja template
SCALAR_TYPE_MAP = {
    DataType.STRING: 'str',
    DataType.INTEGER: 'int',
    DataType.NUMBER: 'float',
    DataType.BOOLEAN: 'bool',
}


class SchemaDataItem:
    '''
    Class used to model the 'data classes' defined in the JSON Schema.
    The class is used in the Jinja2 templates to generate python3
    code leveraging the Strawberry GraphQL module.

    A data 'class' here can be eiter an object/dict, array/list or scalar
    '''

    def __init__(self, class_name: str, schema: Dict, schema_id: str) -> None:

        self.name: str = class_name
        self.schema: Dict = schema
        self.description: str = schema.get('description')
        self.item_id: str = schema.get('$id')
        self.schema_id: str = schema_id
        self.schema_url = urlparse(schema_id)
        self.enabled_apis: Set = set()

        self.type: DataType = DataType(schema['type'])
        self.format: str = self.schema.get('format')
        self.python_type: str = self.get_python_type(class_name, self.schema)

        self.parse_access_permissions()

    def get_python_type(self, data_name: str, data_schema: Dict) -> str:
        '''
        Returns translation of the jsonschema -> python typing string

        :param name: name of the data element
        :param subschema: json-schema blurb for the data element
        :returns: the Python typing value for the data element
        :raises: ValueError, KeyError
        '''

        js_type = data_schema.get('type')
        if not js_type:
            raise ValueError(f'Class {data_name} does not have a type defined')

        try:
            jsonschema_type = DataType(js_type)
        except KeyError:
            raise ValueError(
                f'Data class {data_name} is of unrecognized data type: {js_type}'
            )

        data_format = data_schema.get('format')

        if jsonschema_type not in (DataType.OBJECT, DataType.ARRAY):
            try:
                python_type: str = SCALAR_TYPE_MAP[jsonschema_type]
            except KeyError:
                raise ValueError(
                    f'No GraphQL data type mapping for f{jsonschema_type}'
                )

            if self.type == DataType.STRING:
                if data_format == 'date-time':
                   return 'datetime'
                # elif data_format == 'date':
                #     self.python_type = 'date'
                # elif data_format == 'time':
                #     self.python_type = 'time'
                if (data_format == 'uuid' or self.schema.get('regex') ==
                        (
                            '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}'
                            '-[0-9a-f]{12}$'
                        )):
                    # Note that fastjsonschema does not yet support this format
                    # Switch to https://github.com/marksparkza/jschon ?
                    return 'UUID'
            return python_type
        elif jsonschema_type == DataType.ARRAY:
            items = data_schema.get('items')
            if not items:
                raise ValueError(
                    f'Array {data_name} does not have items defined'
                )

            if 'type' in items:
                return f'List[{SCALAR_TYPE_MAP[DataType(items["type"])]}]'
            elif '$ref' in items:
                if not items['$ref'].startswith('https') and items['$ref'].count('/') != 2:
                    raise ValueError(
                        f'Reference for {data_name} must follow format '
                        f' of "/schema/{data_name}"'
                    )
                class_reference = items['$ref'].split('/')[-1]
                return f'List[{class_reference}'
        elif jsonschema_type == DataType.OBJECT:
            return

        raise ValueError(
            f'Unknown data type for {data_name}: {jsonschema_type}'
        )

    @staticmethod
    def create(class_name: str, schema: Dict, schema_id: str,
               classes: Dict = None):
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

    def parse_access_permissions(self) -> None:
        '''
        Parse the #accesscontrol key of the data item in the JSON Schema
        '''

        # The member always has full permissions to their own data
        self.access_permissions = {
            RightsEntityType.MEMBER: set(
                [
                    DataOperationType.CREATE,
                    DataOperationType.READ,
                    DataOperationType.UPDATE,
                    DataOperationType.DELETE,
                    DataOperationType.APPEND,
                    DataOperationType.SEARCH
                ]
            ),
            RightsEntityType.SERVICE: None,
            RightsEntityType.NETWORK: None,
        }

        rights = self.schema.get('#accesscontrol')
        if not rights:
            return

        if not isinstance(rights, dict):
            raise ValueError(
                f'Access controls must be an object for class {self.name}'
            )

        for entity_type, accessright in rights.items():
            right = DataAccessPermission(entity_type, accessright)

            for action in right.permitted_actions:
                if action in (
                        DataOperationType.CREATE,
                        DataOperationType.UPDATE):
                    self.enabled_apis.add(GraphQlAPI.MUTATE)
                if action == DataOperationType.APPEND:
                    self.enabled_apis.add(GraphQlAPI.APPEND)
                if action == DataOperationType.DELETE:
                    self.enabled_apis.add(GraphQlAPI.DELETE)
                if action == DataOperationType.SEARCH:
                    self.enabled_apis.add(GraphQlAPI.SEARCH)

                if not self.access_permissions[right.entity_type]:
                    self.access_permissions[right.entity_type] = set()

                self.access_permissions[right.entity_type].add(right)

    def has_access(self, entity_type: RightsEntityType, operation: str) -> bool:
        '''
        Checks whether the entity has permission for the operation on the
        data item
        '''

        if isinstance(operation, str):
            operation = DataOperationType(operation)
        elif isinstance(operation, DataOperationType):
            pass
        else:
            raise ValueError('operation must be a str or a DataOperationType')

        return operation in self.access_permissions[entity_type]

class SchemaDataScalar(SchemaDataItem):
    def __init__(self, class_name: str, schema: Dict, schema_id: str) -> None:
        super().__init__(class_name, schema, schema_id)


class SchemaDataObject(SchemaDataItem):
    def __init__(self, class_name: str, schema: Dict, schema_id: str) -> None:
        super().__init__(class_name, schema, schema_id)

        # 'Defined' classes are objects under the '$defs' object
        # of the JSON Schema. We don't create GraphQL mutations for
        # named classes. We require all these 'defined' classes to
        # be defined locally in the schema and their id
        # thus starts with '/schemas/' instead of 'https://'. Furthermore,
        # we require that there no further '/'s in the id

        self.defined_class: bool = False
        if self.item_id:
            self.defined_class = True

        self.fields: List[Dict] = schema['properties']
        self.required_fields: List[str] = schema.get('required')

        self.fields: List[SchemaDataItem] = []
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
            self.fields.append(item)

class SchemaDataArray(SchemaDataItem):
    def __init__(self, class_name: str, schema: Dict, schema_id: str,
                 classes: Dict) -> None:
        super().__init__(class_name, schema, schema_id)

        items = schema.get('items')
        if not items:
            raise ValueError(
                'Schema properties for array {class_name} does not have items '
                'defined'
            )
        if 'type' in items:
            self.items = DataType(items['type'])
            self.referenced_class = None
        elif '$ref' in items:
            self.items = DataType.REFERENCE
            reference = items['$ref']
            url = urlparse(reference)
            if not self.schema_url.scheme == url.scheme:
                raise ValueError(
                    f'Mismatch in URL schema between {self.schema_url} and '
                    f'{reference}'
                )
            if not self.schema_url.netloc == url.netloc:
                raise ValueError(
                    f'Mismatch in URL location between {self.schema_url} and '
                    f'{reference}'
                )
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


class DataAccessPermission:
    def __init__(self, entity_type: str, right: Dict) -> None:
        self.entity_type = RightsEntityType(entity_type)
        self.permitted_actions = set()
        for action in self.permitted_actions:
            self.permitted_actions.add(DataOperationType(action))
