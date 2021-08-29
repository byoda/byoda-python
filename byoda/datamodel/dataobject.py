'''
Class for modeling an element of data of a member
:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import json

from .schema import Schema

MAX_FILE_SIZE = 65536


class DataObject:
    '''
    Generic data object for the data model of services
    '''

    def __init__(self, schema: Schema):
        self._data = None
        self._unvalidated_data = None
        self.schema = schema

    def load_from_file(self, filename: str):

        with open(filename) as file_desc:
            raw_data = file_desc.read(MAX_FILE_SIZE)

        self._unvalidated_data = json.loads(raw_data)

    def validate(self):
        try:
            self._data = self.schema.validate(self._unvalidated_data)
        except Exception:
            raise
