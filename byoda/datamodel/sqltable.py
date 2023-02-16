'''
Class for SQL tables generated based on data classes


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import orjson
import logging
from uuid import UUID
from typing import TypeVar
from datetime import datetime

from byoda.datatypes import DataType

from byoda.datamodel.dataclass import SchemaDataItem
from byoda.datamodel.datafilter import DataFilterSet

_LOGGER = logging.getLogger(__name__)

Sql = TypeVar('Sql')
SqlCursor = TypeVar('SqlCursor')
SqlConnection = TypeVar('SqlConnection')


class SqlTable:
    '''
    Models a SQL table based on a top-level item in the schema for a
    service
    '''

    def __init__(self, data_class: SchemaDataItem, sql_store: Sql,
                 member_id: UUID):
        '''
        Constructor for a SQL table for a top-level item in the schema
        '''

        self.conn: SqlConnection = sql_store.member_db_conns[member_id]
        self.sql_store: Sql = sql_store
        self.member_id: UUID = member_id
        self.table_name: str = SqlTable.get_table_name(data_class.name)
        self.type: DataType = data_class.type
        self.referenced_class: SchemaDataItem | None = None

        self.columns: dict[SchemaDataItem] | None = None

    @staticmethod
    async def setup(data_class: SchemaDataItem,
                    sql_store: Sql, member_id: UUID,
                    data_classes: dict[str, SchemaDataItem] = None):
        '''
        Factory for creating a SqlTable for a data_class
        '''

        if data_class.type == DataType.OBJECT:
            sql_table = ObjectSqlTable(data_class, sql_store, member_id)
        elif data_class.type == DataType.ARRAY:
            sql_table = ArraySqlTable(
                data_class, sql_store, member_id, data_classes
            )
        else:
            raise ValueError(
                'Invalid top-level data class type for '
                f'{data_class.name}: {data_class.type}'
            )

        await sql_table.create()

        return sql_table

    @staticmethod
    def get_native_datatype(val: str | DataType) -> str:
        if isinstance(val, DataType):
            val = val.value

        return {
            'string': 'TEXT',
            'integer': 'INTEGER',
            'number': 'REAL',
            'boolean': 'INTEGER',
            'uuid': 'TEXT',
            'date-time': 'REAL',
            'array': 'BLOB',
            'reference': 'TEXT',
        }[val.lower()]

    async def create(self):
        '''
        Create the table
        '''

        stmt: str = f'CREATE TABLE IF NOT EXISTS {self.table_name}('

        for column in self.columns.values():
            stmt += f'{column.storage_name} {column.storage_type}, '

        stmt = stmt.rstrip(', ') + ') STRICT'

        await self.sql_store.execute(stmt, self.member_id)

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
        Normalizes the value returned by Sqlite3 to the python type for
        the JSONSchema type specified in the schema of the service
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

    def _normalize_row(self, row: list[dict[str, object]]
                       ) -> dict[str, object]:
        '''
        Normalizes the row returned by Sqlite3 to the python type for
        the JSONSchema type specified in the schema of the service
        '''

        result: dict[str, object] = {}
        for column_name in row.keys():
            field_name = SqlTable.get_field_name(column_name)
            result[field_name] = \
                self.columns[field_name].normalize(row[column_name])

        return result

    @staticmethod
    def get_table_name(table: str) -> str:
        return f'_{table}'

    @staticmethod
    def get_column_name(field: str) -> str:
        '''
        Returns the name of the SQL column for a JSONSchema field
        '''

        if field.startswith('_'):
            return field
        else:
            return f'_{field}'

    def get_field_name(column: str) -> str:
        '''
        Returns the name of the JSONSchema field for an SQL column
        '''
        return column.lstrip('_')

    def sql_values_clause(self, data: dict, separator: str = '='
                          ) -> tuple[str, dict[str, object]]:
        '''
        Gets the 'values' part of an SQL INSERT or SQL UPDATE statement

        :param data: the values that will be used for the placeholders
        in the statement
        :param separator: the separator between the list of columns and
        the list of placeholders

        '''

        stmt: str = '('
        values: dict[str, object] = {}

        for column in self.columns.values():
            value = data.get(column.name)
            # We only include columns for which a value is available
            # in the 'data' dict
            if value:
                # Add the column to the list of columns
                stmt += f'{column.storage_name}, '

                # Normalize value to type expected by the database
                if column.storage_type == 'INTEGER':
                    value = int(value)
                elif column.storage_type == 'REAL':
                    # We store date-time values as an epoch timestamp
                    if (hasattr(column, 'format')
                            and column.format == 'date-time'):
                        if isinstance(value, str):
                            value = datetime.fromisoformat(value).timestamp()
                        elif isinstance(value, datetime):
                            value = value.timestamp()
                        elif type(value) in (int, float):
                            pass
                        else:
                            raise ValueError(
                                f'Invalid type {type(value)} for '
                                f'date-time value: {value}'
                            )
                    else:
                        value = float(value)
                elif column.storage_type == 'TEXT':
                    if type(value) in (list, dict):
                        # For nested objects or arrays, we store them as JSON
                        value = orjson.dumps(value).decode('utf-8')
                    else:
                        value = str(value)

                values[column.storage_name] = value

        stmt = stmt.rstrip(', ') + f') {separator} ('
        for column in self.columns.values():
            if data.get(column.name):
                stmt += f':{column.storage_name}, '

        stmt = stmt.rstrip(', ') + ') '

        return stmt, values

    def sql_where_clause(self, data_filters: DataFilterSet) -> str:
        return data_filters.sql_where_clause()


class ObjectSqlTable(SqlTable):
    def __init__(self, data_class: SchemaDataItem, sql_store: Sql,
                 member_id: UUID):
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

        super().__init__(data_class, sql_store, member_id)
        self.columns: dict[SchemaDataItem] = data_class.fields

        for column in self.columns.values():
            column.storage_name = SqlTable.get_column_name(column.name)
            column.storage_type = SqlTable.get_native_datatype(column.type)

    async def query(self, data_filter_set: DataFilterSet = None,
                    first: int = None, after: int = None,
                    ) -> list[dict[str, object]]:
        '''
        Get the data from the table. As this is an object table,
        only 0 or 1 rows of results are expected

        :param data_filter_set: filters to apply to the SQL query
        :param first: number of objects to return
        :param after: offset to start returning objects from

        :returns: list of dict with data for the row in the table
        '''

        # Note: parameters data_filter_set, first & after are ignored for
        # 'object' SQL tables as it does not make sense for SQL queries for
        # 'objects'. However, it does make sense for recursive GraphQL queries
        # so that's why they may have a values

        stmt = f'SELECT * FROM {self.table_name}'

        rows = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=None,
            autocommit=False, fetchall=True
        )

        if len(rows) == 0:
            return None
        elif len(rows) > 1:
            _LOGGER.error(
                f'Query for {self.table_name} returned more than one row'
            )

        result = self._normalize_row(rows[0])

        if result:
            return [result]
        else:
            return []

    async def mutate(self, data: dict, data_filter_set: DataFilterSet = None
                     ) -> int:
        '''
        Sets the data for the object. If existing data is present, any value
        will be wiped if not present in the supplied data

        :returns: dict with data for the row in the table or None
        if no data was in the table
        '''

        if data_filter_set:
            raise ValueError(
                f'query of object {self.table_name} does not support query '
                'parameters'
            )

        # Tables for objects only have a single row so to mutate the data,
        # we delete that row and then insert a new one. This means the
        # supplied data must include for all fields in the table. Any
        # field in the table not in the data will be set to an empty or 0
        # value
        # SqLite 'UPSERT' does not work here as it depends on a constraint
        # violation for detecting an existing row. We may not have constraints
        # in the data model for the field in the service schema
        stmt = f'DELETE FROM {self.table_name}'
        await self.sql_store.execute(
            stmt, member_id=self.member_id, data=None, autocommit=False
        )

        stmt = f'INSERT INTO {self.table_name} '
        values: dict[str, object] = {}

        values_stmt, values_data = self.sql_values_clause(
            data, separator='VALUES'
        )

        stmt += values_stmt
        values |= values_data

        result = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=values,
            autocommit=True
        )

        return result.rowcount


class ArraySqlTable(SqlTable):
    def __init__(self, data_class: SchemaDataItem, sql_store: Sql,
                 member_id: UUID, data_classes: list[SchemaDataItem]):
        '''
        Constructor for a SQL table for a top-level arrays in the schema
        '''

        if not data_classes:
            raise ValueError(
                f'Data class {data_class.name} is an array but no data '
                'classes have been specified'
            )

        if data_class.defined_class:
            raise ValueError(
                f'Defined class {data_class.name} can not be an array'
            )

        super().__init__(data_class, sql_store, member_id)

        self.referenced_class = data_class.referenced_class
        if self.referenced_class.name not in data_classes:
            raise ValueError(
                f'Data class {data_class.name} references class '
                f'{self.referenced_class.name}, which does not exist'
            )

        self.columns: dict[SchemaDataItem] = \
            data_classes[self.referenced_class.name].fields

        for data_item in self.columns.values():
            adapted_type = data_item.type
            if adapted_type in (DataType.OBJECT, DataType.ARRAY):
                adapted_type = DataType.STRING

            data_item.storage_name = SqlTable.get_column_name(data_item.name)
            data_item.storage_type = SqlTable.get_native_datatype(adapted_type)

    async def query(self, data_filters: DataFilterSet = None,
                    first: int = None, after: int = None,
                    ) -> None | list[dict[str, object]]:
        '''
        Get one of more rows from the table

        :param data_filter_set: filters to apply to the SQL query
        :param first: number of objects to return
        :param after: offset to start returning objects from
        '''

        stmt = f'SELECT * FROM {self.table_name} '

        placeholders = {}
        if data_filters:
            where_clause, where_data = self.sql_where_clause(data_filters)
            stmt += where_clause
            placeholders |= where_data

        rows = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=placeholders,
            autocommit=False, fetchall=True
        )

        if len(rows) == 0:
            return None

        # Reconcile results with the field names in the Schema
        results = []
        for row in rows:
            result = self._normalize_row(row)
            results.append(result)

        return results

    async def append(self, data: dict) -> int:
        '''
        Append a row to the table
        '''

        stmt = f'INSERT INTO {self.table_name} '
        values: dict[str, object] = {}

        values_stmt, values_data = self.sql_values_clause(
            data, separator='VALUES'
        )

        stmt += values_stmt
        values |= values_data

        result = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=values,
            autocommit=True
        )

        return result.rowcount

    async def mutate(self, data: dict, data_filters: DataFilterSet
                     ) -> int:
        '''
        Mutates ones or more records. For SQL Arrays, mutation is
        implemented using SQL UPDATE
        '''

        return await self.update(data, data_filters)

    async def update(self, data: dict, data_filters: DataFilterSet
                     ) -> int:
        '''
        updates ones or more records
        '''

        stmt = f'UPDATE {self.table_name} SET '
        values: dict[str, object] = {}

        values_clause, values_data = self.sql_values_clause(data)
        stmt += values_clause
        values |= values_data

        where_clause, filter_data = self.sql_where_clause(data_filters)
        stmt += where_clause
        values |= filter_data

        result: SqlCursor = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=values,
            autocommit=True
        )
        return result.rowcount

    async def delete(self, data_filters: DataFilterSet) -> int:
        '''
        Deletes one or more records based on the provided filters
        '''

        stmt = f'DELETE FROM {self.table_name} '
        values: dict[str, object] = {}

        if data_filters:
            where_clause, filter_data = self.sql_where_clause(data_filters)
            stmt += where_clause
            values |= filter_data

        result: SqlCursor = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=values, autocommit=True
        )

        return result.rowcount
