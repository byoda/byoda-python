'''
Class for managing persistent storage of top-level data elements
in the service schema. This is currently a placeholder and will
be implemented once additional storage technologies other than
SQL will be supported

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from uuid import UUID
from hashlib import sha1
from logging import Logger
from logging import getLogger
from datetime import datetime
from collections import namedtuple

from byoda.datamodel.datafilter import DataFilterSet
_LOGGER: Logger = getLogger(__name__)

# These are columns we add to all tables to track
# the source of the information, ie. the member_id
# or service_id or app_id that appended/mutated the data,
# or in the case of pod workers, from who the data was
# sourced
META_ID_COLUMN: str = 'id'
META_ID_TYPE_COLUMN: str = 'id_type'
# This is a column that we add to each table to support
# pagination
META_CURSOR_COLUMN: str = 'cursor'

META_COLUMNS: dict[str, str] = {
    META_CURSOR_COLUMN: 'TEXT',
    META_ID_COLUMN: 'TEXT',
    META_ID_TYPE_COLUMN: 'TEXT',
}

# These are columns that we add to 'cache-only' tables. It
# contains the timestamp after which the row should be deleted,
# the member we received the data from and from which class
# the data was received
CACHE_EXPIRE_COLUMN: str = 'expires'
CACHE_ORIGIN_CLASS_COLUMN: str = 'origin_class_name'

CACHE_COLUMNS: dict[str, str] = {
    CACHE_EXPIRE_COLUMN: 'REAL',
    CACHE_ORIGIN_CLASS_COLUMN: 'TEXT',
}

ResultMetaData = namedtuple(
    'ResultMetaData', [
        META_CURSOR_COLUMN,
        META_ID_COLUMN,
        META_ID_TYPE_COLUMN,
        CACHE_EXPIRE_COLUMN,
        CACHE_ORIGIN_CLASS_COLUMN
    ]
)

ResultData = dict[str, object]

QueryResult = namedtuple('QueryResult', ['data', 'metadata'])
QueryResults = list[QueryResult]


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
        '''
        Returns the name of the table
        '''

        raise NotImplementedError

    @staticmethod
    def get_column_name(field: str) -> str:
        '''
        Returns the name of the column in the table for a JSONSchema field
        '''

        raise NotImplementedError

    @staticmethod
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

    @staticmethod
    def get_cursor_hash(data: dict, origin_id: UUID | str | None,
                        field_names: list[str]) -> str:
        '''
        Helper function to generate cursors for objects based on the
        stringified values of the required fields of object

        :param data: the data to generate the cursor for
        :param origin_id: the origin ID to include in the cursor
        :param field_names: the names of the fields to include in the cursor
        :returns: the cursor
        '''

        hash_gen = sha1()
        for field_name in field_names:
            value: bytes = str(data.get(field_name, '')).encode('utf-8')
            hash_gen.update(value)

        if origin_id:
            hash_gen.update(str(origin_id).encode('utf-8'))

        cursor: str = hash_gen.hexdigest()

        return cursor[0:8]

    def expire(self, timestamp: datetime | None = None) -> any:
        '''
        Expires content from a table

        :param timestamp: use this timestamp instead of the current time
        to see if content is expired
        '''

        raise NotImplementedError
