'''
Class for modeling the (JSON) schema to validating data

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import json

import fastjsonschema

MAX_SCHEMA_SIZE = 1000000


class Schema:
    def __init__(self, jsonschema_filename):
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

        # This is a callable to validate data against the schema
        self.validate = None

        self.load(jsonschema_filename)

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

    def validate(self, data: dict):
        '''
        Validates the provided data

        :param data: data to validate
        :returns: validated data
        :raises:
        '''

        return self.validate(data)
