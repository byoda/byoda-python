'''
Class for SQL tables generated based on data classes


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import re


from copy import copy
from uuid import UUID
from typing import TypeVar
from datetime import datetime
from datetime import timezone
from logging import getLogger

import orjson

from byoda.datamodel.table import QueryResult

from byoda.datamodel.table import META_COLUMNS
from byoda.datamodel.table import META_CURSOR_COLUMN
from byoda.datamodel.table import META_ID_COLUMN
from byoda.datamodel.table import META_ID_TYPE_COLUMN
from byoda.datamodel.table import CACHE_COLUMNS
from byoda.datamodel.table import CACHE_EXPIRE_COLUMN
from byoda.datamodel.table import CACHE_ORIGIN_CLASS_COLUMN

from byoda.datatypes import IdType
from byoda.datatypes import DataType
from byoda.datatypes import CounterFilter

from byoda.datamodel.dataclass import SchemaDataItem
from byoda.datamodel.dataclass import SchemaDataScalar
from byoda.datamodel.dataclass import SchemaDataArray

from byoda.datamodel.datafilter import DataFilterSet

from byoda.util.logger import Logger

from .table import Table

_LOGGER: Logger = getLogger(__name__)

Sql = TypeVar('Sql')
SqlCursor = TypeVar('SqlCursor')
SqlConnection = TypeVar('SqlConnection')

# This is the built-in SQLite column name for the rowid that we
# use for pagination
SQLITE_ROWID_COLUMN_NAME: str = 'rowid'

RX_SQL_SAFE_VALUE = re.compile(r'^[a-zA-Z0-9_]+$')


class SqlTable(Table):
    '''
    Models a SQL table based on a top-level item in the schema for a
    service
    '''

    __slots__ = [
        'class_name', 'sql_store', 'member_id', 'table_name', 'type',
        'referenced_class', 'columns', 'cache_only', 'expires_after'
    ]

    def __init__(self, data_class: SchemaDataItem, sql_store: Sql,
                 member_id: UUID):
        '''
        Constructor for a SQL table for a top-level item in the schema
        '''

        self.class_name: str = data_class.name

        # Should data in this table be periodically expired and purged?
        self.cache_only: bool = data_class.cache_only

        # Time (in seconds) after which data should be purged from the cache
        self.expires_after: int | None = data_class.expires_after

        self.sql_store: Sql = sql_store
        self.member_id: UUID = member_id
        self.table_name: str = SqlTable.get_table_name(data_class.name)
        self.type: DataType = data_class.type
        self.referenced_class: SchemaDataItem | None = \
            data_class.referenced_class

        self.columns: dict[SchemaDataItem] | None = None

    @staticmethod
    async def setup(data_class: SchemaDataItem,
                    sql_store: Sql, member_id: UUID):
        '''
        Factory for creating a SqlTable for a data_class
        '''

        if data_class.type == DataType.OBJECT:
            sql_table = ObjectSqlTable(data_class, sql_store, member_id)
        elif data_class.type == DataType.ARRAY:
            sql_table = ArraySqlTable(data_class, sql_store, member_id)
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
            'object': 'BLOB',
            'reference': 'TEXT',
        }[val.lower()]

    async def create(self) -> None:
        '''
        Create the table
        '''

        stmt: str = f'CREATE TABLE IF NOT EXISTS {self.table_name}('

        for column in self.columns.values():
            stmt += f'{column.storage_name} {column.storage_type}, '

        # We calculate a hash for each row, which is used for pagination
        column_name: str
        column_type: str
        for column_name, column_type in META_COLUMNS.items():
            stmt += f'{column_name} {column_type}, '

        # SqlTable can be used for cache-only content. In that case, we
        # add an 'expires' column to the table and make sure it is updated
        # every time we append or mutate data
        if self.cache_only:
            stmt += f'{CACHE_EXPIRE_COLUMN} REAL, '
            stmt += f'{CACHE_ORIGIN_CLASS_COLUMN} TEXT, '

        stmt = stmt.rstrip(', ') + ') STRICT'

        await self.sql_store.execute(stmt, self.member_id)

        await self.reconcile_table_columns()

    async def reconcile_table_columns(self) -> None:
        '''
        When a table has been modified in a new version of the schema,
        new columns may have been added and the above 'CREATE TABLE'
        would not add them to existing tables. So we add them to
        the table with this method.
        '''

        rows = await self.sql_store.execute(
            f'PRAGMA table_info("{self.table_name}");',
            self.member_id, fetchall=True
        )
        sql_columns = {row['name']: row['type'] for row in rows}

        for column in self.columns.values():
            if type(column) in (SchemaDataScalar, SchemaDataArray):
                await self.reconcile_column(
                    column, sql_columns.get(column.storage_name)
                )

        await self.reconcile_meta_columns(sql_columns)

        if self.cache_only:
            await self.reconcile_cache_only_columns(sql_columns)

    async def reconcile_column(self,
                               column: SchemaDataScalar | SchemaDataArray,
                               current_sql_type: str | None) -> None:
        '''
        Ensure a field in the data class is present in the table, has the
        correct data type and, if specified, is indexed

        :raises: ValueError if the data type of an existing column has changed
        '''

        if current_sql_type and column.storage_type != current_sql_type:
            raise ValueError(
                f'Can not convert existing SQL column {column.storage_name} '
                f'from {column.storage_type} to {current_sql_type} in table '
                f'{self.table_name}'
            )

        if not current_sql_type:
            stmt = (
                f'ALTER TABLE {self.table_name} '
                f'ADD COLUMN {column.storage_name} {column.storage_type};'
            )
            await self.sql_store.execute(stmt, self.member_id)

        if (isinstance(column, SchemaDataScalar)
                and (column.is_index
                     or column.is_counter
                     or column.format == 'uuid')):
            stmt = (
                f'CREATE INDEX IF NOT EXISTS '
                f'BYODA_IDX_{self.table_name}_{column.name} '
                f'ON {self.table_name}({column.storage_name})'
            )
            await self.sql_store.execute(stmt, self.member_id)
            _LOGGER.debug(
                f'Created index on {self.table_name}:{column.storage_name}'
            )

    async def reconcile_meta_columns(self, sql_columns: dict[str, str]):
        for column_name, column_type in META_COLUMNS.items():
            if column_name not in sql_columns:
                stmt = (
                    f'ALTER TABLE {self.table_name} '
                    f'ADD COLUMN {column_name} {column_type};'
                )
                await self.sql_store.execute(stmt, self.member_id)

            if column_name in (META_ID_COLUMN, META_CURSOR_COLUMN):
                stmt = (
                    f'CREATE INDEX IF NOT EXISTS '
                    f'BYODA_IDX_{self.table_name}_{column_name} '
                    f'ON {self.table_name}({column_name})'
                )
                _LOGGER.debug(
                    f'Created index on {self.table_name}:{column_name}'
                )

    async def reconcile_cache_only_columns(self, sql_columns: dict[str, str]):
        for column_name, column_type in CACHE_COLUMNS.items():
            if column_name not in sql_columns:
                stmt = (
                    f'ALTER TABLE {self.table_name} '
                    f'ADD COLUMN {column_name} {column_type};'
                )
                await self.sql_store.execute(stmt, self.member_id)

            if column_name in (CACHE_EXPIRE_COLUMN):
                stmt = (
                    f'CREATE INDEX IF NOT EXISTS '
                    f'BYODA_IDX_{self.table_name}_{column_name} '
                    f'ON {self.table_name}({column_name})'
                )
                await self.sql_store.execute(stmt, self.member_id)
                _LOGGER.debug(
                    f'Created index on {self.table_name}:{column_name}'
                )

    async def query(self, data_filter_set: DataFilterSet):
        '''
        Get data matching the specified criteria
        '''

        raise NotImplementedError

    async def mutate(self, data: dict, data_filters: DataFilterSet = None):
        '''
        Update data matching the specified criteria
        '''

        raise NotImplementedError

    async def append(self, data: dict):
        '''
        Insert data into the table
        '''

        raise NotImplementedError

    async def delete(self, data_filters: DataFilterSet):
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
                       ) -> tuple[dict[str, object],
                                  dict[str, str | int | float]]:
        '''
        Normalizes the row returned by Sqlite3 to the python type for
        the JSONSchema type specified in the schema of the service

        '''

        result: dict[str, object] = {}
        meta: dict[str, str | int | float] = {}
        for column_name in row.keys():
            value = row[column_name]
            if (column_name in META_COLUMNS
                    or column_name == SQLITE_ROWID_COLUMN_NAME
                    or column_name in CACHE_COLUMNS):
                if value:
                    meta[column_name] = value
                continue

            field_name = SqlTable.get_field_name(column_name)
            field: SchemaDataItem = self.columns[field_name]
            result[field_name] = field.normalize(value)

        return result, meta

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

    @staticmethod
    def convert_to_storage_type(column: str, value: object) -> object:
        '''
        Converts the value to the type expected by the database
        '''

        # Normalize value to python type expected by the database driver
        if value is None:
            return None
        elif column.storage_type == 'TEXT':
            return str(value)
        elif column.storage_type == 'INTEGER':
            return int(value)
        elif column.storage_type == 'REAL':
            # We store date-time values as an epoch timestamp
            if (hasattr(column, 'format')
                    and column.format == 'date-time'):
                if isinstance(value, str):
                    if value[-1] == 'Z':
                        value = f'{value[:-1]}+00:00'
                    return datetime.fromisoformat(value).timestamp()
                elif isinstance(value, datetime):
                    return value.timestamp()
                elif type(value) in (int, float):
                    pass
                else:
                    raise ValueError(
                        f'Invalid type {type(value)} for '
                        f'date-time value: {value}'
                    )
            else:
                return float(value)
        elif column.storage_type == 'BLOB':
            if type(value) in (list, dict):
                # For nested objects or arrays, we store them as JSON
                try:
                    return orjson.dumps(value)
                except TypeError as exc:
                    _LOGGER.warning(
                        f'Could not convert {value} to JSON: {exc}'
                    )
                    raise

        return value

    def sql_values_clause(self, data: dict[str, object], cursor: str,
                          origin_id: UUID | None,
                          origin_id_type: IdType | None,
                          origin_class_name: str | None, separator: str = '='
                          ) -> tuple[str, dict[str, object]]:
        '''
        Gets the 'values' part of an SQL INSERT or SQL UPDATE statement

        :param data: the values that will be used for the placeholders
        in the statement
        :param separator: the separator between the list of columns and
        the list of placeholders

        '''

        values: dict[str, object] = {}

        # We first generate the list of variables
        column: SchemaDataItem
        stmt: str = '('
        for column in self.columns.values():
            value: str = data.get(column.name)

            # We only include columns for which a value is available
            # in the 'data' dict
            if value is None:
                continue

            # Add the column to the list of columns
            stmt += f'{column.storage_name}, '

            db_value: object = self.convert_to_storage_type(column, value)

            values[column.storage_name] = db_value

        if cursor:
            stmt += f'{META_CURSOR_COLUMN}, '
            values[META_CURSOR_COLUMN] = cursor

        if origin_id and origin_id_type:
            stmt += f'{META_ID_COLUMN}, {META_ID_TYPE_COLUMN}, '
            values[META_ID_COLUMN] = str(origin_id)
            values[META_ID_TYPE_COLUMN] = origin_id_type.value

        if self.cache_only:
            stmt += CACHE_EXPIRE_COLUMN
            now: datetime = datetime.now(tz=timezone.utc).timestamp()
            values[CACHE_EXPIRE_COLUMN] = now + self.expires_after

            if origin_class_name is not None:
                stmt += f', {CACHE_ORIGIN_CLASS_COLUMN}'
                values[CACHE_ORIGIN_CLASS_COLUMN] = origin_class_name

        # Now we generate the 'placeholders' part of the statement
        stmt = stmt.rstrip(', ') + f') {separator} ('
        for column in self.columns.values():
            if data.get(column.name) is not None:
                stmt += f':{column.storage_name}, '

        if cursor:
            stmt += f':{META_CURSOR_COLUMN}, '

        if origin_id and origin_id_type:
            stmt += f':{META_ID_COLUMN}, :{META_ID_TYPE_COLUMN}, '

        if self.cache_only:
            stmt += f':{CACHE_EXPIRE_COLUMN}, '

            if origin_class_name is not None:
                stmt += f':{CACHE_ORIGIN_CLASS_COLUMN}, '

        stmt = stmt.rstrip(', ') + ') '

        return stmt, values

    def sql_where_clause(self, data_filters: DataFilterSet) -> str:
        '''
        Generate SQL where clause for the data filters
        '''

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

    @property
    def required_fields(self) -> set[str]:
        '''
        :returns: the set of required fields for the array
        '''

        required_fields: set[str] = set(
            [
                field.name for field in self.columns.values()
                if field.required
            ]
        )

        return required_fields

    def get_cursor_hash(self, data: dict[str, object], origin_member_id: UUID
                        ) -> str:
        '''
        Returns the cursor for the data. The cursor can be used
        to select the data from the table

        :param data: the data for the object
        :param origin_member_id: the member_id of the member that provided
        the data
        :returns: str
        '''

        return Table.get_cursor_hash(
            data, origin_member_id, self.required_fields
        )

    async def query(self, data_filter_set: DataFilterSet = None,
                    first: int = None, after: int = None,
                    fields: set[str] | None = None,
                    meta_filters: DataFilterSet | None = None,
                    ) -> list[QueryResult] | None:
        '''
        Get the data from the table. As this is an object table,
        only 0 or 1 rows of results are expected

        :param data_filter_set: filters to apply to the SQL query
        :param first: number of objects to return
        :param after: offset to start returning objects from

        :returns: list of tuples of the data and its metadata
        '''

        # Note: parameters data_filter_set, first & after are ignored for
        # 'object' SQL tables as it does not make sense for SQL queries for
        # 'objects'. However, it does make sense for recursive Data API queries
        # so that's why they may have values

        query_fields: str = ''
        for field in fields or []:
            data_class = self.columns.get(field)
            if not data_class or not _is_sql_safe_value(field):
                raise ValueError('Invalid field name: {field}')

            if (data_class.type == DataType.OBJECT
                    and not data_class.referenced_class.is_scalar):
                continue

            query_fields += self.get_column_name(field) + ', '

        query_fields = query_fields.rstrip(', ')

        if not query_fields:
            query_fields = '*'

        stmt = f'SELECT rowid, {query_fields} FROM {self.table_name} '

        rows = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=None,
            autocommit=False, fetchall=True
        )

        if len(rows) == 0:
            return None
        elif len(rows) > 1:
            _LOGGER.error(
                f'Query for {self.table_name} returned more than one row: '
                f'{rows}'
            )

        result, meta = self._normalize_row(rows[0])

        if result:
            return [(result, meta)]
        else:
            return []

    async def mutate(self, data: dict, cursor: str, origin_id: UUID | None,
                     origin_id_type: IdType | None,
                     origin_class_name: str | None,
                     data_filters: DataFilterSet = None) -> int:
        '''
        Sets the data for the object. If existing data is present, any value
        will be wiped if not present in the supplied data

        :returns: dict with data for the row in the table or None
        if no data was in the table
        '''

        if data_filters:
            raise ValueError(
                f'mutation of object {self.table_name} does not support data '
                'filters'
            )

        # Tables for objects only have a single row so to mutate the data,
        # we delete that row and then insert a new one. This means the
        # supplied data must include for all fields in the table. Any
        # field in the table not in the data will be set to an empty or 0
        # value
        # SqLite 'UPSERT' does not work here as it depends on a constraint
        # violation for detecting an existing row. We may not have constraints
        # in the data model for the field in the service schema
        stmt: str = f'DELETE FROM {self.table_name}'
        await self.sql_store.execute(
            stmt, member_id=self.member_id, data=None, autocommit=True
        )

        stmt = f'INSERT INTO {self.table_name} '
        values: dict[str, object] = {}

        values_stmt: str
        values_data: dict[str, object]
        values_stmt, values_data = self.sql_values_clause(
            data=data, cursor=cursor,
            origin_id=origin_id, origin_id_type=origin_id_type,
            origin_class_name=origin_class_name,
            separator='VALUES'
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
                 member_id: UUID):
        '''
        Constructor for a SQL table for a top-level arrays in the schema
        '''

        if data_class.defined_class:
            raise ValueError(
                f'Defined class {data_class.name} can not be an array'
            )

        super().__init__(data_class, sql_store, member_id)

        self.columns: dict[str, SchemaDataItem] = self.referenced_class.fields

        for data_item in self.columns.values():
            adapted_type = data_item.type

            data_item.storage_name = SqlTable.get_column_name(data_item.name)
            data_item.storage_type = SqlTable.get_native_datatype(adapted_type)

    @property
    def required_fields(self) -> set[str]:
        '''
        Returns the list of required fields for the array
        '''

        if not self.referenced_class:
            raise ValueError('This array does not reference objects')

        return self.referenced_class.required_fields

    def get_cursor_hash(self, data: dict[str, object], origin_memeber_id: UUID
                        ) -> str:
        '''
        Returhs the cursor (hash) for the required fields of the data
        '''

        if not self.referenced_class:
            raise ValueError('This array does not reference objects')

        return self.referenced_class.get_cursor_hash(data, origin_memeber_id)

    async def count(self, counter_filter: CounterFilter) -> int:
        '''
        Gets the number of items from the array stored in the table

        :param counter_filter: list of field/value pairs to filter the
        data
        '''

        stmt = f'SELECT COUNT(ROWID) AS counter FROM {self.table_name}'

        data = {}
        if counter_filter:
            stmt += ' WHERE'
            for field_name, value in counter_filter.items():
                column_name = self.get_column_name(field_name)
                stmt += f' {column_name} = :{column_name}'
                data[column_name] = value

        rows = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=data, fetchall=True)

        row_count = rows[0]['counter']

        return row_count

    async def query(self, data_filters: DataFilterSet = None,
                    first: int = None, after: str = None,
                    fields: set[str] | None = None,
                    meta_filters: DataFilterSet | None = None,
                    ) -> list[QueryResult] | None:
        '''
        Get one of more rows from the table normalized to the
        python types for the JSONSchema types specified in the schema

        :param data_filter_set: filters to apply to the SQL query
        :param first: number of objects to return
        :param after: offset to start returning objects from
        :param fields: fields to include in the response
        :param meta_filters: filters to apply to the metadata
        :returns: list of tuples of the data and its metadata
        '''

        query_fields: str = ''
        for field in fields or []:
            data_class = self.columns.get(field)
            if not data_class or not _is_sql_safe_value(field):
                raise ValueError('Invalid field name: {field}')

            query_fields += self.get_column_name(field) + ', '

        query_fields = query_fields.rstrip(', ')

        if not query_fields:
            query_fields = '*'

        stmt: str = f'SELECT rowid, {query_fields} FROM {self.table_name} '

        placeholders: dict[str, str] = {}

        where_clause: str | None = None
        if data_filters and data_filters.filters:
            where_data: dict[str, object]
            where_clause, where_data = self.sql_where_clause(data_filters)
            stmt += where_clause
            placeholders |= where_data

        if meta_filters and meta_filters.filters:
            meta_where_clause: str
            meta_where_data: dict[str, object]
            meta_where_clause, meta_where_data = self.sql_where_clause(
                meta_filters
            )

            if where_clause:
                # Non-meta data filter was also supplied so we don't want to
                # include 'WHERE' clause for both regular filter and
                # meta-filter
                meta_where_clause = meta_where_clause.lstrip('WHERE') + 'AND '

            stmt += meta_where_clause
            placeholders |= meta_where_data

        if after:
            # Pagination is implemented using the SQLite 'rowid' column
            stmt = await self._add_cursor_to_query(
                stmt, placeholders, after, data_filters
            )

        if first:
            stmt += ' LIMIT :first '
            placeholders['first'] = first

        rows = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=placeholders,
            autocommit=False, fetchall=True
        )

        if len(rows) == 0:
            return None

        # Reconcile results with the field names in the Schema
        results = []
        for row in rows:
            result, meta = self._normalize_row(dict(row))
            results.append(QueryResult(data=result, metadata=meta))

        return results

    async def _add_cursor_to_query(self, stmt: str,
                                   placeholders: dict[str, object], after: str,
                                   data_filters: DataFilterSet
                                   ) -> str:
        '''
        Adds to SQL query to return rows after the specified cursor. Updates
        provided 'placeholders' dict with value for the Sqlite3 'row_id'
        column

        :param stmt: SQL statement to add the cursor to
        :param placeholders: placeholders for the SQL statement
        :param after: cursor to return rows after
        :param data_filters: filters to apply to the SQL query
        :returns: the updated SQL statement
        '''

        cursor_stmt: str = stmt
        if data_filters and data_filters.filters:
            cursor_stmt += ' AND '
        else:
            cursor_stmt += 'WHERE '

        cursor_stmt += 'cursor = :cursor LIMIT 1'
        cursor_placeholders: dict[str, str] = copy(placeholders)
        cursor_placeholders['cursor'] = after

        rows = await self.sql_store.execute(
            cursor_stmt, member_id=self.member_id,
            data=cursor_placeholders, autocommit=False, fetchall=True
        )

        updated_stmt: str = stmt
        if rows:
            if data_filters and data_filters.filters:
                updated_stmt += ' AND '
            else:
                updated_stmt += 'WHERE '

            updated_stmt += 'rowid > :row_id ORDER BY rowid ASC '
            placeholders['row_id'] = rows[0]['rowid']
        else:
            # If cursor is no longer valid then we act as if
            # no cursor was specified with the 'after' parameter
            _LOGGER.debug(
                f'Cursor {after} not found in table {self.table_name}'
            )
            pass

        return updated_stmt

    async def append(self, data: dict[str, object], cursor: str,
                     origin_id: UUID, origin_id_type: IdType,
                     origin_class_name: str) -> int:
        '''
        Append a row to the table

        :param data: k/v pairs for data to be stored in the table
        :param cursor: pagination cursor calculated for the data
        :returns: the number of rows added to the table
        '''

        stmt: str = f'INSERT INTO {self.table_name} '
        values: dict[str, object] = {}

        values_stmt, values_data = self.sql_values_clause(
            data=data, cursor=cursor,
            origin_id=origin_id, origin_id_type=origin_id_type,
            origin_class_name=origin_class_name,
            separator='VALUES'
        )

        stmt += values_stmt
        values |= values_data

        result = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=values,
            autocommit=True
        )

        return result.rowcount

    async def mutate(self, data: dict, cursor: str, origin_id: UUID,
                     origin_id_type: IdType, origin_class_name: str,
                     data_filters: DataFilterSet) -> int:
        '''
        Mutates ones or more records. For SQL Arrays, mutation is
        implemented using SQL UPDATE

        :param data: k/v pairs for data to be stored in the table
        :param data_filters: filters to select the rows to update
        :param origin_id: the ID of the source for the data
        :param origin_id_type: the type of ID of the source for the data
        :returns: the number of rows mutated to the table
        '''

        return await self.update(
            data, cursor, data_filters, origin_id, origin_id_type,
            origin_class_name
        )

    async def update(self, data: dict, cursor: str,
                     data_filters: DataFilterSet,
                     origin_id: UUID | None, origin_id_type: IdType | None,
                     origin_class_name: str | None) -> int:
        '''
        updates ones or more records

        :param data: k/v pairs for data to be stored in the table
        :param cursor: pagination cursor calculated for the data
        :param data_filters: filters to select the rows to update
        :param origin_id: the ID of the source for the data
        :param origin_id_type: the type of ID of the source for the data
        :param origin_class_name: the class that the data was sourced from
        :returns: the number of rows mutated to the table
        '''

        stmt = f'UPDATE {self.table_name} SET '
        values: dict[str, object] = {}

        values_clause, values_data = self.sql_values_clause(
            data=data, cursor=cursor,
            origin_id=origin_id, origin_id_type=origin_id_type,
            origin_class_name=origin_class_name
        )
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

    async def expire(self, timestamp: int | float | datetime | None = None
                     ) -> int:
        '''
        Expires data in a 'cache_only' table. Calling this method does
        not update counters and updates

        :param timestamp: the timestamp (in seconds) before which data should
        be deleted. If not specified, the current time plus the expiration time
        specified for the data class is used
        :returns: number of items deleted from the table
        :raises: ValueError if the table is not a 'cache_only' table
        '''

        if not self.cache_only:
            raise ValueError(
                'Can not expire data in non-cache_only '
                f'table: {self.class_name}'
            )

        seconds: float | int
        if not timestamp:
            # We add 900 seconds to the current time so we'll delete data that
            # expires in the next 15 minutes
            seconds: float = datetime.now(tz=timezone.utc).timestamp() + 900
        elif isinstance(timestamp, datetime):
            seconds = timestamp.timestamp()
        elif type(timestamp) in (int, float):
            seconds = timestamp
        else:
            raise ValueError(f'Invalid timestamp type: {type(timestamp)}')

        stmt: str = (
            f'DELETE FROM {self.table_name} '
            f'WHERE {CACHE_EXPIRE_COLUMN} <= :timestamp'
        )
        data: dict[str, float | int] = {'timestamp': seconds}

        result = await self.sql_store.execute(
            stmt, member_id=self.member_id, data=data, autocommit=True
        )

        return result.rowcount


def _is_sql_safe_value(field: str) -> bool:
    '''
    Checks whether the field name is safe to include as-is in an SQL query
    '''
    if RX_SQL_SAFE_VALUE.match(field):
        return True
    else:
        return False
