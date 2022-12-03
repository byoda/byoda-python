'''
Class for SQL tables generated based on data classes


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

from byoda.datatypes import DataType
from byoda.datamodel.dataclass import SchemaDataItem
from byoda.datamodel.datafilter import DataFilterSet
from byoda.storage.sqlite import Connection as SqlConnection

_LOGGER = logging.getLogger(__name__)


class SqlTable:
    '''
    Models a SQL table based on a top-level item in the schema for a
    service
    '''

    def __init__(self, conn: SqlConnection, data_class: SchemaDataItem):
        '''
        Constructor for a SQL table for a top-level item in the schema
        '''

        self.conn = conn
        self.table_name: str = SqlTable.get_table_name(data_class.name)
        self.table_fields: dict[str, DataType] = {}
        self.type: DataType = data_class.type

    @staticmethod
    def setup(conn: SqlConnection, data_class: SchemaDataItem,
              data_classes: dict[str, SchemaDataItem] = None):
        '''
        Factory for creating a SqlTable for a data_class
        '''

        if data_class.type == DataType.OBJECT:
            sql_table = ObjectSqlTable(conn, data_class)
        elif data_class.type == DataType.ARRAY:
            sql_table = ArraySqlTable(conn, data_class, data_classes)
        else:
            raise ValueError(
                'Invalid top-level data class type for '
                f'{data_class.name}: {data_class.type}'
            )

        return sql_table

    def query(self, data_filter_set: DataFilterSet):
        '''
        Get data matching the specified criteria
        '''

        raise NotImplementedError

    def update(self, data_filter_set: DataFilterSet, data: dict):
        '''
        Update data matching the specified criteria
        '''

        raise NotImplementedError

    def insert(self, data: dict):
        '''
        Insert data into the table
        '''

        raise NotImplementedError

    def delete(self, data_filter_set: DataFilterSet):
        '''
        Delete data matching the specified criteria
        '''

        raise NotImplementedError

    @staticmethod
    def get_table_name(table: str) -> str:
        return f'_{table}'

    @staticmethod
    def get_column_name(field: str) -> str:
        return f'_{field}'

    def get_field_name(column: str) -> str:
        return column.lstrip('_')


class ObjectSqlTable(SqlTable):
    def __init__(self, data_class: SchemaDataItem):
        '''
        Constructor for a SQL table for a top-level objects in the schema
        '''
        if data_class.defined_class:
            raise ValueError(
                'We do not create tables for referenced classes: '
                f'{data_class.name}'
            )
        if data_class.referenced_class:
            raise ValueError(
                f'Referenced classes for data class {data_class.name} '
                'are not supported for objects'
            )

        super().__init__(data_class)
        for field_name, field_type in data_class.fields.items():
            column_name = SqlTable.get_column_name(field_name)
            self.table_fields[column_name] = field_type

    def query(self, data_filter_set: DataFilterSet = None
              ) -> None | dict[str, object]:
        '''
        Get the data from the table. As this is an object table,
        only 0 or 1 rows of results are expected

        :returns: dict with data for the row in the table or None
        if no data was in the table
        '''

        if data_filter_set:
            raise ValueError(
                f'query of object {self.table_name} does not support query '
                'parameters'
            )

        stmt = f'SELECT * FROM {self.table_name}'
        rows = self.conn.execute_fetchall(stmt)
        if len(rows) == 0:
            return None
        elif len(rows) > 1:
            _LOGGER.error(
                f'Query for {self.table_name} returned more than one row'
            )

        result = {}
        for column, value in rows[0].items():
            result[SqlTable.get_field_name(column)] = value

        return result

    def mutate(self, data: dict, data_filter_set: DataFilterSet = None):
        '''
        Get the data from the table. As this is an object table,
        only 0 or 1 rows of results are expected

        :returns: dict with data for the row in the table or None
        if no data was in the table
        '''

        if data_filter_set:
            raise ValueError(
                f'query of object {self.table_name} does not support query '
                'parameters'
            )

        data = self.query()
        if data:
            stmt = f'UPDATE {self.table_name} SET'
        else:
            stmt = f'INSERT INTO '

class ArraySqlTable(SqlTable):
    def __init__(self, data_class: SchemaDataItem,
                 data_classes: list[SchemaDataItem]):
        '''
        Constructor for a SQL table for a top-level arrays in the schema
        '''

        if data_class.defined_class:
            raise ValueError(
                f'Defined class {data_class.name} can not be an array'
            )

        super().__init__(data_class)
        referenced_class = data_class.referenced_class
        if referenced_class not in data_classes:
            raise ValueError(
                f'Data class {data_class.name} references class '
                f'{referenced_class}, which does not exist'
            )

        fields = data_classes[referenced_class].fields
        for field_name, field_type in fields.items():
            column_name = SqlTable.get_column_name(field_name)
            self.table_fields[column_name] = field_type
