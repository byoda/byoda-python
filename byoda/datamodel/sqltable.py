'''
Class for SQL tables generated based on data classes


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import orjson
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
        self.data_class: SchemaDataItem = data_class

        # Python sqlLite3 module does not support prepared statements?
        # self.query_cache = dict[str, str]

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

    def normalize(self, value: object, column: str):
        '''
        Normalizes the value returned by Sqlite3 to the type
        specified in the schema of the service
        '''

        field_name = SqlTable.get_field_name(column)
        if field_name not in self.data_class.fields:
            raise ValueError(
                f'Field {field_name} not found in data class '
                f'{self.data_class.name}'
            )

        field: SchemaDataItem = self.data_class.fields[field_name]
        result = field.normalize(value)
        return result

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
            adapted_type = field_type.type
            if adapted_type in (DataType.OBJECT, DataType.ARRAY):
                raise ValueError(
                    'Object and array types are not supported for '
                    f'{field_name}'
                )

            self.table_fields[column_name] = adapted_type

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
            result[SqlTable.get_field_name(column)] = self.normalize(value, column)

        return result

    def mutate(self, data: dict[str, str],
               data_filter_set: DataFilterSet = None):
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

        self.conn.execute(f'DELETE FROM {self.table_name}', autocommit=False)

        self.append(data, autocommit=True)

    def update(self, data: dict[str, str], data_filter_set: DataFilterSet):
        '''
        Updates a row in the table
        '''

        pass

    def append(self,  data: dict[str, str], autocommit: bool = True):
        '''
        Adds a row to the table
        '''

        stmt = f'INSERT INTO {self.table_name} '
        fields = list(data.keys())
        for key in data:
            column_name = SqlTable.get_column_name(key)
            if column_name not in self.table_columns:
                raise ValueError(
                    f'Data has key {key} not present in the '
                    f'SQL table {self.table_name}'
                )

            stmt += f'{column_name}, '

        stmt = stmt.rstrip(', ') + ') VALUES ('
        adapted_values = []
        for key in data:
            stmt += '?, '
            if self.data_class[key].type in (DataType.OBJECT, DataType.ARRAY):
                adapted_values.append(orjson.dumps(data[key]))
        stmt = stmt.rstrip(', ') + ')'

        self.conn.execute(stmt, tuple(data.values()), autocommit=autocommit)


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
            adapted_type = field_type.type
            if adapted_type in (DataType.OBJECT, DataType.ARRAY):
                adapted_type = DataType.STRING

            self.table_fields[column_name] = field_type
