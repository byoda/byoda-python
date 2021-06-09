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
    def __init__(self):
        '''
        Construct a schema
        '''

        self.jsonschema = None
        self.jsonschema_validate = None

    def load(self, filename):
        '''
        Load a schema from a file
        '''

        with open(filename) as file_desc:
            data = file_desc.read(MAX_SCHEMA_SIZE)

        self.jsonschema_validate = fastjsonschema.compile(json.loads(data))

    def validate(self, data: dict):
        '''
        Validates the provided data

        :param data: data to validate
        :returns: validated data
        :raises:
        '''

        return self.jsonschema_validate(data)
