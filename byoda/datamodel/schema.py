'''
Class for modeling the (JSON) schema to validating data

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

from abc import abstractmethod
import sys
import json
import logging
from copy import deepcopy
from typing import List, Dict, Set, TypeVar
from types import ModuleType
from collections import OrderedDict

import jinja2

import fastjsonschema
from fastjsonschema import JsonSchemaValueException
from byoda.secrets.network_data_secret import NetworkDataSecret
from byoda.secrets.service_data_secret import ServiceDataSecret     # noqa: F401

from byoda.util import MessageSignature
from byoda.util import ServiceSignature
from byoda.util import NetworkSignature
from byoda.util import SignatureType

from byoda.secrets import Secret, DataSecret

from byoda.storage import FileStorage

_LOGGER = logging.getLogger(__name__)

Service = TypeVar('Service')

MAX_SCHEMA_SIZE = 1000000
SCHEMA_TEMPLATE = 'podserver/files'
CODEGEN_DIRECTORY = 'podserver/codegen'

# Translation from jsondata data type to Python data type in the Jinja template
TYPE_MAP = {
    'string': 'str',
    'integer': 'int',
    'number': 'float',
    'boolean': 'bool',
}


class Schema:
    def __init__(self, schema: dict):
        '''
        Construct a schema. The number of class properties is kept
        to a minimum to avoid these properties from getting out of
        sync with the json schema.

        The signatures on the data contract will not
        be checked in the constructor as we do not know yet what the
        service_id is of the schema and this means we can't use the data
        secret yet of that service to verify the signature.
        '''

        # This is the schema as read and deserialized from a file to a dict
        self.json_schema: Dict = schema

        # Note that we have getters/setters for the top-level properties
        if self.service_id is None:
            raise ValueError('Schema must have a Service ID')

        if self.version is None:
            raise ValueError('Schema must have a version')

        if not self.name:
            raise ValueError('Schema must have a name')

        if not self.supportemail:
            raise ValueError('Schema must have a support email address')

        # We have to have a value for all top level fields otherwise
        # schema signature verification will fail
        if not self.description:
            raise ValueError('Schema must have a description')

        if not self.owner:
            raise ValueError('Schema must have an owner')

        if not self.website:
            raise ValueError('Schema must have a website')

        # The GraphQL schema as generated by this class
        self.gql_schema: List = []

        self.verified_signatures: Set[MessageSignature] = set()

        # This is a callable to validate data against the JSON schema
        self.validate: fastjsonschema.validate = None

        self.service_data_secret: ServiceDataSecret = None
        self.network_data_secret: NetworkDataSecret = None

    @staticmethod
    def get_schema(filepath: str, storage_driver: str,
                   service_data_secret: ServiceDataSecret,
                   network_data_secret: NetworkDataSecret):
        '''
        Facory to read schema from a file
        '''
        data = storage_driver.read(filepath)
        json_schema = json.loads(data)

        schema = Schema(json_schema)
        schema.service_data_secret = service_data_secret
        schema.network_data_secret = network_data_secret

        schema.load()

        return schema

    def as_string(self):
        '''
        Returns the schema as a string of json data presented
        for creating or verifying a signature for the schema
        '''

        return json.dumps(self.json_schema, sort_keys=True, indent=4)

    def load(self):
        '''
        Load a schema from a dict
        '''

        try:
            self.service_signature = ServiceSignature.from_dict(
                self.json_schema['signatures'].get(
                    SignatureType.SERVICE.value
                ),
                data_secret=self.service_data_secret

            )
        except ValueError:
            _LOGGER.warning(
                'No Service signature in contract for service '
                f'{self.service_id}'
            )
            raise

        try:
            self.network_signature = NetworkSignature.from_dict(
                self.json_schema['signatures'].get(
                    SignatureType.NETWORK.value
                ),
                data_secret=self.network_data_secret
            )
        except ValueError:
            _LOGGER.warning(
                'No Network signature in contract for service '
                f'{self.service_id}'
            )
            raise

        self.validate = fastjsonschema.compile(self.json_schema['jsonschema'])

    def save(self, filepath: str, storage_driver: FileStorage):
        '''
        Write a schema to a JSON file, ie. when an account becomes
        a member of the service that the schema belongs to
        '''

        storage_driver.write(filepath, self.as_string())

    def create_signature(self, secret: DataSecret,
                         signature_type: SignatureType,
                         hash_algo: str = 'SHA256') -> None:
        '''
        Generate a signature for the data contract. The network will only
        sign a service contract if:
        - the service already has signed it.
        - TODO: the network did not sign a data contract for the service with
        the same version number
        '''

        if 'signatures' not in self.json_schema:
            self.json_schema['signatures'] = {}

        if self.json_schema['signatures'].get(SignatureType.NETWORK.value):
            raise ValueError('Network signature already exists')

        if signature_type == SignatureType.SERVICE:
            if self.json_schema['signatures'].get(SignatureType.SERVICE.value):
                raise ValueError('Service signature already exists')

            message_signature = ServiceSignature(secret, hash_algo=hash_algo)
        else:
            message_signature = NetworkSignature(secret, hash_algo=hash_algo)

        schema_str = self.as_string()
        message_signature.sign_message(schema_str)

        # Add the signature to the original JSON Schema
        self.json_schema['signatures'][signature_type.value] = \
            message_signature.as_dict()

    def verify_signature(self, secret: Secret, signature_type: SignatureType,
                         hash_algo: str = 'SHA256'):
        '''
        Verifies the signature of the data contract. The signature by the
        service only covers the data contract, the signature by the network
        covers both the data contract and the signature by the service.
        :raises: ValueError
        '''

        schema = self.json_schema

        if 'signatures' not in schema:
            raise ValueError('No signatures in the schema')

        # signature_type.value might be 'service' in which case
        # we check the same thing twice but that's ok
        if (SignatureType.SERVICE.value not in schema['signatures']
                or (signature_type == SignatureType.NETWORK and
                    SignatureType.NETWORK.value not in schema['signatures'])):
            raise ValueError(
                f'Missing signature in JSON Schema: {signature_type.value}'
            )

        original_schema = None
        if SignatureType.NETWORK.value in schema['signatures']:
            # A signature of a schema never covers the network signature so
            # we remove it from the schema
            original_schema = deepcopy(schema)
            signature = NetworkSignature.from_dict(
                schema['signatures'].pop(SignatureType.NETWORK.value),
                data_secret=self.network_data_secret
            )

        if signature_type == SignatureType.SERVICE:
            if not original_schema:
                original_schema = deepcopy(schema)
            # A signature of a schema by a service does not cover the
            # signature of the service so we temporarily remove it
            signature = ServiceSignature.from_dict(
                schema['signatures'].pop(
                    SignatureType.SERVICE.value
                ),
                data_secret=self.service_data_secret
            )

        schema_str = self.as_string()
        signature.verify_message(schema_str, secret, hash_algo=hash_algo)

        # Restore the original schema after we popped the signature
        self.json_schema = original_schema

        self.verified_signatures.add(signature_type)

    def generate_graphql_schema(self):
        '''
        Generates code to enable GraphQL schema to be generated using Graphene.
        The logic is:
        - we start with the json parsed (not the jsonschema) by Schema.load()
        - we call a Jinja template to generate source code in a python
        - we execute the generated source code and extract the resulting
          instance
        '''

        if not (SignatureType.NETWORK in self.verified_signatures
                and SignatureType.SERVICE in self.verified_signatures):
            raise ValueError('Schema signatures have not been verified')

        loader = jinja2.FileSystemLoader(SCHEMA_TEMPLATE)
        environment = jinja2.Environment(
            loader=loader,
            extensions=['jinja2.ext.do', 'jinja2.ext.loopcontrols'],
            trim_blocks=True,
            autoescape=True
        )
        template = environment.get_template('graphene_schema.jinja')

        code_filename = (
            f'{CODEGEN_DIRECTORY}/service_{self.service_id}_graphql.py'
        )

        classes = self.get_graphene_classes()

        code = template.render(
            service_id=self.service_id,
            classes=classes, type_map=TYPE_MAP
        )

        with open(code_filename, 'w') as file_desc:
            file_desc.write(code)

        # We compile the generated python source file. For multi-line code,
        # you must use the 'exec' mode of compile()
        code = compile(code, code_filename, 'exec')

        # This trick keeps the result of the parsed code out of globals()
        # and locals()
        module_name = f'Query{self.service_id}'
        module = ModuleType(module_name)

        # we need to add the module to the list of modules otherwise
        # introspection by Strawberry module fails
        sys.modules[module_name] = module

        # Now we execute the code as being part of the module we generated
        exec(code, module.__dict__)

        # Here we can the function of the module to extract the schema
        self.gql_schema = module.get_schema()

    def get_graphene_classes(self) -> List[Dict[str, Dict]]:
        '''
        Finds all objects in the JSON schema for which we will
        need to generated classes that are derived from Graphene.ObjectType
        class
        '''

        properties = self.json_schema['jsonschema']['properties']

        classes = OrderedDict()
        self._get_graphene_classes(classes, properties)

        return classes

    def _get_graphene_classes(self, classes: List[Dict[str, object]],
                              properties: Dict):
        for field, field_properties in properties.items():
            if field_properties.get('type') == 'object':
                classes.update({field: field_properties['properties']})
                self._get_graphene_classes(
                    classes, field_properties['properties']
                )

    # Getter/Setters for
    # - service_id
    # - version
    # - name
    # - description
    # - owner
    # - website
    # - supportemail
    # - service_signature
    # - network_signature
    # - signatures (only has a getter)

    @property
    def service_id(self):
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['service_id']

    @service_id.setter
    def service_id(self, value):
        if not isinstance(value, int):
            try:
                value = int(value)
            except ValueError:
                raise ValueError(
                    f'Service ID must be an int, not of type {type(value)}'
                )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['service_id'] = value

    @property
    def version(self):
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['version']

    @version.setter
    def version(self, value):
        if not isinstance(value, int):
            try:
                value = int(value)
            except ValueError:
                raise ValueError(
                    f'Version must be an int, not of type {type(value)}'
                )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['version'] = value

    @property
    def name(self):
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['name']

    @name.setter
    def name(self, value):
        if value and not isinstance(value, str):
            raise ValueError(
                f'Version must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['name'] = value

    @property
    def description(self):
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['description']

    @description.setter
    def description(self, value):
        if value and not isinstance(value, str):
            raise ValueError(
                f'Description must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['description'] = value

    @property
    def owner(self):
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['owner']

    @owner.setter
    def owner(self, value):
        if value and not isinstance(value, str):
            raise ValueError(
                f'Name must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['owner'] = value

    @property
    def website(self):
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['website']

    @website.setter
    def website(self, value):
        if value and not isinstance(value, str):
            raise ValueError(
                f'Name must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['website'] = value

    @property
    def supportemail(self):
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['supportemail']

    @supportemail.setter
    def supportemail(self, value):
        if value and not isinstance(value, str):
            raise ValueError(
                f'Support email must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['supportemail'] = value

    @property
    def network_signature(self) -> MessageSignature:
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        network_signature = self.json_schema['signatures'].get('network')
        if not network_signature:
            raise ValueError('No network signature avaiable')

        return network_signature.get['signature']

    @network_signature.setter
    def network_signature(self, value: MessageSignature):
        if value and not isinstance(value, MessageSignature):
            raise ValueError(
                'Support email must be an MessageSignature, '
                f'not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        network_signature = self.json_schema['signatures'].get('network')
        if not network_signature:
            self.json_schema['signatures']['network'] = {}

        self.json_schema['signatures']['network'] = value.as_dict()

    @property
    def service_signature(self) -> MessageSignature:
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        service_signature = self.json_schema['signatures'].get('service')
        if not service_signature:
            raise ValueError('No service signature avaiable')

        return service_signature.get['signature']

    @service_signature.setter
    def service_signature(self, value: MessageSignature):
        if value and not isinstance(value, MessageSignature):
            raise ValueError(
                f'service_signature must be an MessageSignature, '
                f'not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        service_signature = self.json_schema['signatures'].get('service')
        if not service_signature:
            self.json_schema['signatures']['service'] = {}

        self.json_schema['signatures']['service'] = value.as_dict()

    @property
    def signatures(self):
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['signatures']
