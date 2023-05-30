'''
Class for managing persistent storage of top-level data elements
in the service schema. This is currently a placeholder and will
be implemented once additional storage technologies other than
SQL will be supported

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from byoda.datamodel.datafilter import DataFilterSet


_LOGGER = logging.getLogger(__name__)


class Table:
    async def query(self, data_filter_set: DataFilterSet):
        '''
        Get data matching the specified criteria
        '''

        raise NotImplementedError

    async def mutate(self, data: dict, data_filter_set: DataFilterSet = None):
        '''
        Update data matching the specified criteria
        '''

        raise NotImplementedError

    async def append(self, data: dict):
        '''
        Insert data into the table
        '''

        raise NotImplementedError

    async def delete(self, data_filter_set: DataFilterSet):
        '''
        Delete data matching the specified criteria
        '''

        raise NotImplementedError

    def normalize(self, value: object, column: str):
        '''
        Normalize the data retrieved from the storage layer to
        the python type for the JSONSchema type specified in the schema
        of the service
        '''

        raise NotImplementedError

    @staticmethod
    def get_table_name(table: str) -> str:
        raise NotImplementedError

    @staticmethod
    def get_column_name(field: str) -> str:
        '''
        Returns the name of the column in the table for a JSONSchema field
        '''

        raise NotImplementedError

    def get_field_name(column: str) -> str:
        '''
        Returns the name of the JSONSchema field for a column in the table
        '''

        raise NotImplementedError

    @staticmethod
    def convert_to_storage_type(column: str, value: object) -> object:
        '''
        Converts the value to the type expected by the database
        '''

        raise NotImplementedError
