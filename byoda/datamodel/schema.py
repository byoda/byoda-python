'''
Class for modeling the (JSON) schema to validating data

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import json
from copy import deepcopy
from typing import List, Dict
from types import ModuleType
from collections import OrderedDict

import jinja2

import fastjsonschema

from byoda.util import MessageSignature
from byoda.util import ServiceSignature
from byoda.util import NetworkSignature
from byoda.util import SignatureType
from byoda.util.secrets import Secret, DataSecret


MAX_SCHEMA_SIZE = 1000000
SCHEMA_TEMPLATE = 'podserver/files'
CODEGEN_DIRECTORY = 'podserver/codegen'


class Schema:
    def __init__(self, jsonschema_filepath: str, storage_driver: str):
        '''
        Construct a schema. The signatures on the data contract will not
        be checked as we do not know yet what the service_id is of the
        schema and this can't yet use the data secret of that service
        to verify the signature.
        '''

        # This is the original JSON data from the
        # schema file
        self.service = None
        self.service_id = None

        # The signatures for the schema
        self.signatures: Dict[SignatureType, MessageSignature] = {
            SignatureType.SERVICE: None,
            SignatureType.NETWORK: None,
        }

        self.json_schema = {}
        self.gql_schema = []

        # This is a callable to validate data against the schema
        self.validate: fastjsonschema.validate = None

        self.storage_driver = storage_driver
        self.load(jsonschema_filepath)

    def load(self, filepath: str):
        '''
        Load a schema from a file
        '''

        data = self.storage_driver.read(filepath)

        self.json_schema = json.loads(data)
        self.name = self.json_schema['name']
        self.service_id = self.json_schema['service_id']

        try:
            self.signatures[SignatureType.SERVICE] = \
                ServiceSignature.from_dict(
                    self.json_schema['signatures'].get(
                        SignatureType.SERVICE.value
                    )
                )
        except ValueError:
            pass

        try:
            self.signatures[SignatureType.NETWORK] = \
                NetworkSignature.from_dict(
                    self.json_schema['signatures'].get(
                        SignatureType.NETWORK.value
                    )
                )
        except ValueError:
            pass

        self.validate = fastjsonschema.compile(self.json_schema['jsonschema'])

    def save(self, filepath):
        '''
        Write a schema to a JSON file, ie. when an account becomes
        a member of the service that the schema belongs to
        '''

        self.storage_driver.write(
            filepath, json.dumps(self.json_schema, indent=4, sort_keys=True)
        )

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

            message_signature = ServiceSignature(secret)
        else:
            message_signature = NetworkSignature(secret)

        message_signature.sign_message(
            json.dumps(self.json_schema, sort_keys=True, indent=4)
        )

        # Add the signature to the original JSON Schema
        self.json_schema['signatures'][signature_type.value] = \
            message_signature.as_dict()

        self.signatures[signature_type] = message_signature

    def verify_signature(self, secret: Secret, signature_type: SignatureType,
                         hash_algo: str = 'SHA256'):
        '''
        Verifies the signature of the data contract. The signature by the
        service only covers the data contract, the signature by the network
        covers both the data contract and the signature by the service.
        '''

        schema = deepcopy(self.json_schema)

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

        # A signature of a schema never covers the network signature so
        # we remove it from the schema
        if SignatureType.NETWORK.value in schema['signatures']:
            signature = NetworkSignature.from_dict(
                schema['signatures'].pop(SignatureType.NETWORK.value)
            )

        if signature_type == SignatureType.SERVICE:
            # A signature of a schema by a service does not cover the
            # signature of the service
            signature = ServiceSignature.from_dict(
                schema['signatures'].pop(SignatureType.SERVICE.value)
            )

        signature.verify_message(schema, secret)

        self.signatures[signature_type] = signature

    def generate_graphql_schema(self):
        '''
        Generates code to enable GraphQL schema to be generated using Graphene.
        The logic is:
        - we start with the json parsed (not the jsonschema) by Schema.load()
        - we call a Jinja template to generate source code in a python
        - we execute the generated source code and extract the resulting
          instance
        '''

        if not (self.signatures[SignatureType.NETWORK].verified
                and self.signatures[SignatureType.SERVICE].verified):
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
            classes=classes
        )

        with open(code_filename, 'w') as file_desc:
            file_desc.write(code)

        # We compile the generated python source file. For multi-line code,
        # you must use the 'exec' mode of compile()
        code = compile(code, code_filename, 'exec')

        # This trick keeps the result of the parsed code out of globals()
        # and locals()
        module = ModuleType(f'Query{self.service_id}')

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
        classes = OrderedDict({'Query': properties})

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
