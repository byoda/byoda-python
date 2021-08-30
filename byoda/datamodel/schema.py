'''
Class for modeling the (JSON) schema to validating data

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import json

from types import ModuleType

from jinja2 import Template

import fastjsonschema


MAX_SCHEMA_SIZE = 1000000
SCHEMA_TEMPLATE = 'podserver/files/graphene_schema.jinja2'
CODEGEN_DIRECTORY = 'podserver/codegen'


class Schema:
    def __init__(self, jsonschema_filepath):
        '''
        Construct a schema
        '''

        self.jsonschema = None
        self.jsonschema_validate = None
        self.service = None
        self.service_id = None

        # This is the original JSON data from the
        # schema file
        self.schema_data = None

        self.gql_schema = None

        # This is a callable to validate data against the schema
        self.validate = None

        self.load(jsonschema_filepath)

    def load(self, filepath):
        '''
        Load a schema from a file
        '''

        with open(filepath) as file_desc:
            data = file_desc.read(MAX_SCHEMA_SIZE)

        self.schema_data = json.loads(data)
        self.name = self.schema_data['name']
        self.service_id = self.schema_data['service_id']
        self.service_signature = self.schema_data['service_signature']
        self.validate = fastjsonschema.compile(self.schema_data)
        self.generate_graphql_schema()

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
        - we call a Jinja2 template to generate source code in a python
        - we execute the generated source code and extract the resulting
          instance
        '''

        with open(SCHEMA_TEMPLATE) as file_desc:
            template = Template(
                file_desc.read(),
                trim_blocks=True,
                autoescape=True
            )

        code_filename = (
            f'{CODEGEN_DIRECTORY}/service_{self.service_id}_graphql.py'
        )
        code = template.render(
            service_id=self.service_id,
            schema=self.schema_data['schema']
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
