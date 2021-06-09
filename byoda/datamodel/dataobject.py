'''
Class for modeling an element of data in of an member
:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import json

from .schema import Schema

MAX_FILE_SIZE = 65536


class DataObject:
    '''
    Generic data object for the data model of serices
    '''

    def __init__(self, schema: Schema):
        self._data = None
        self.schema = schema

    def load_from_file(self, filename):

        with open(filename) as file_desc:
            raw_data = file_desc.read(MAX_FILE_SIZE)

        data = json.loads(raw_data)

        try:
            self._data = self.schema.validate(data)
        except Exception:
            raise
