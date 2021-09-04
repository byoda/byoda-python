'''
Class for modeling the (JSON) schema to validating data

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import json
from typing import List, Dict
from types import ModuleType
from collections import OrderedDict

import jinja2

import fastjsonschema


MAX_SCHEMA_SIZE = 1000000
SCHEMA_TEMPLATE = 'podserver/files'
CODEGEN_DIRECTORY = 'podserver/codegen'


class Schema:
    def __init__(self, jsonschema_filepath, storage_driver):
        '''
        Construct a schema
        '''

        self.jsonschema = None
        self.jsonschema_validate = None
        self.service = None
        self.service_id = None

        # This is the original JSON data from the
        # schema file
        self.schema_data = []

        self.gql_schema = []

        # This is a callable to validate data against the schema
        self.validate = None

        self.storage_driver = storage_driver
        self.load(jsonschema_filepath)

    def load(self, filepath):
        '''
        Load a schema from a file
        '''

        data = self.storage_driver.read(filepath)

        self.schema_data = json.loads(data)
        self.name = self.schema_data['name']
        self.service_id = self.schema_data['service_id']
        self.service_signature = self.schema_data['service_signature']
        self.validate = fastjsonschema.compile(self.schema_data)
        self.generate_graphql_schema()

    def save(self, filepath):
        '''
        Write a schema to a JSON file, ie. when an account becomes
        a member of the service that the schema belongs to
        '''

        self.storage_driver.write(
            filepath, json.dumps(self.schema_data, indent=4)
        )

    def validate(self, data: dict):
        '''
        Validates the provided data

        :param data: data to validate
        :returns: validated data
        :raises:
        '''

        return self.validate(data)

    def generate_graphql_schema(self):
        '''
        Generates code to enable GraphQL schema to be generated using Graphene.
        The logic is:
        - we start with the json parsed (not the jsonschema) by Schema.load()
        - we call a Jinja template to generate source code in a python
        - we execute the generated source code and extract the resulting
          instance
        '''

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

        properties = self.schema_data['schema']['properties']
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
