'''
Class for SQL tables generated based on data classes


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
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

from byoda.storage.sqlite import Connection as SqlConnection

_LOGGER = logging.getLogger(__name__)

Sql = TypeVar('Sql')


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
            'array': 'TEXT',
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
        if field.startswith('_'):
            return field
        else:
            return f'_{field}'

    def get_field_name(column: str) -> str:
        return column.lstrip('_')


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

    async def query(self, data_filter_set: DataFilterSet = None
                    ) -> None | dict[str, object]:
        '''
        Get the data from the table. As this is an object table,
        only 0 or 1 rows of results are expected

        :returns: dict with data for the row in the table or None
        if no data was in the table
        '''

        stmt = f'SELECT * FROM {self.table_name}'
        rows = await self.conn.execute_fetchall(stmt)
        if len(rows) == 0:
            return None
        elif len(rows) > 1:
            _LOGGER.error(
                f'Query for {self.table_name} returned more than one row'
            )

        # Reconcile results with the field names in the Schema
        result = {}
        for column_name in rows[0].keys():
            field_name = SqlTable.get_field_name(column_name)
            result[field_name] = \
                self.columns[field_name].normalize(rows[0][column_name])

        return result

    async def mutate(self, data: dict, data_filter_set: DataFilterSet = None):
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

        values = []
        stmt = f'INSERT INTO {self.table_name}('
        for column in self.columns.values():
            stmt += f'{column.storage_name}, '
            value = data.get(column.name)
            if column.storage_type == 'INTEGER':
                if value:
                    value = int(value)
            elif column.storage_type == 'REAL':
                if value:
                    if column.format == 'date-time':
                        value = value.timestamp()
                    else:
                        value = float(value)
            elif column.storage_type == 'TEXT':
                if value:
                    if type(value) in (list, dict):
                        value = orjson.dumps(value)
                    else:
                        value = str(value)
                else:
                    value = ''

            values.append(value)

        stmt = stmt.rstrip(', ') + ') VALUES ('
        for column in self.columns.values():
            stmt += '?, '

        stmt.rstrip(', ') + ')'

        stmt = stmt.rstrip(', ') + ')'

        await self.sql_store.execute(
            stmt, member_id=self.member_id, data=values,
            autocommit=True
        )


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

    async def query(self, data_filters: DataFilterSet = None
                    ) -> None | list[dict[str, object]]:
        '''
        Get one of more rows from the table
        '''

        sql_filters: list[str] = []
        if data_filters:
            for data_filter in data_filters.filters.values():
                for filter in data_filter:
                    sql_filters.append(filter.sql_filter())

        stmt = f'SELECT * FROM {self.table_name}'
        if sql_filters:
            stmt = stmt + ' WHERE ' + ' AND '.join(sql_filters)

        rows = await self.conn.execute_fetchall(stmt)
        if len(rows) == 0:
            return None

        # Reconcile results with the field names in the Schema
        results = []
        for row in rows:
            result = {}
            for column_name in row.keys():
                field_name = SqlTable.get_field_name(column_name)
                result[field_name] = \
                    self.columns[field_name].normalize(row[column_name])
            results.append(result)

        return results

    async def append(self, data: dict):
        '''
        Append a row to the table
        '''

        values = []
        stmt = f'INSERT INTO {self.table_name}('
        for column in self.columns.values():
            stmt += f'{column.storage_name}, '
            value = data.get(column.name)
            if column.storage_type == 'INTEGER':
                if value:
                    value = int(value)
            elif column.storage_type == 'REAL':
                if value:
                    if column.format == 'date-time':
                        value = datetime.fromisoformat(value).timestamp()
                    else:
                        value = float(value)
            elif column.storage_type == 'TEXT':
                if value:
                    if type(value) in (list, dict):
                        value = orjson.dumps(value)
                    else:
                        value = str(value)
                else:
                    value = ''

            values.append(value)

        stmt = stmt.rstrip(', ') + ') VALUES ('
        for column in self.columns.values():
            stmt += '?, '

        stmt.rstrip(', ') + ')'

        stmt = stmt.rstrip(', ') + ')'

        return await self.sql_store.execute(
            stmt, member_id=self.member_id, data=values,
            autocommit=True
        )

    async def update(self, data: dict, data_filters: DataFilterSet):
        '''
        Updates ones or more records
        '''