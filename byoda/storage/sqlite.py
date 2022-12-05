'''
There is both a generic SQL and a SqliteStorage class. The generic SQL
class takes care of converting the data schema of a service to a SQL table.
The SqliteStorage class takes care of persisting the data.

Each membership of a service gets its own SqlLite DB file under the
root-directory, ie.: /byoda/sqlite/<member_id>.db

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import logging
from uuid import UUID
from sqlite3 import Row
from typing import TypeVar
from datetime import datetime

import aiosqlite
from aiosqlite.core import Connection

from byoda.datatypes import DataType
from byoda.datamodel.dataclass import SchemaDataItem
from byoda.datamodel.sqltable import SqlTable

from byoda.util.paths import Paths

from byoda import config

Member = TypeVar('Member')
Schema = TypeVar('Schema')

_LOGGER = logging.getLogger(__name__)


class Sql:
    def __init__(self):
        self.account_db_conn: Connection | None = None

        self.member_db_conns: dict[str, Connection] = {}

    def connection(self, member_id: UUID = None) -> Connection:
        if not member_id:
            con: Connection = self.account_db_conn

            _LOGGER.debug('Using account DB connection')
        else:
            con: Connection = self.member_db_conns.get(
                member_id
            )
            _LOGGER.debug(
                f'Using member DB connection for member_id {member_id}'
            )
            if not con:
                raise ValueError(f'No DB for member_id {member_id}')

        return con

    def cursor(self, member_id: UUID = None) -> aiosqlite.cursor.Cursor:
        '''
        Returns a cursor for the account DB or the member DB for the member_id,
        if provided
        '''

        con = self.connection(member_id)
        cur = con.cursor()
        return cur

    async def execute(self, command: str, vars: list[str] = None,
                      member_id: UUID = None, autocommit: bool = True
                      ) -> list[Row]:
        '''
        Executes the provided command over the connection for the SqLite DB
        for the membership. If no member ID is provided, the SqLite DB for
        the account will be used.

        The list of values for the 'vars' parameter will be used to replace
        any placeholders in the SQL command.
        '''

        con = self.connection(member_id)

        result = await con.execute(command, vars)

        if autocommit:
            await con.commit()

        return result

    def get_table_definitions(self, data_classes: dict[str, SchemaDataItem]
                              ) -> dict[str, list[str]]:
        '''
        Returns the table definitions for the schema
        '''

        sql_tables: dict[str, SqlTable] = {}
        for data_class in data_classes.values():
            if data_class.type == DataType.OBJECT:
                if not data_class.defined_class:
                    sql_table = SqlTable.setup(data_class)
                else:
                    _LOGGER.debug(f'Skipping defined class {data_class.name}')
                    continue
            elif data_class.type == DataType.ARRAY:
                sql_table = SqlTable.setup(data_class, data_classes)
            else:
                raise ValueError(
                    f'Invalid top-level data class type: {data_class.name} -> '
                    f'{data_class.type}')

            sql_tables[sql_table.table_name] = {}
            for field_name, field_type in sql_table.fields.items():
                column_name = self.get_column_name(field_name)
                sql_tables[sql_table.name][column_name] = field_type

        return sql_tables


#
# Sqlite adapters and converters
#
def adapt_datetime_epoch(val: datetime):
    '''
    Adapt datetime.datetime to Unix timestamp.
    '''
    return int(val.timestamp())


def convert_timestamp(val):
    """Convert Unix epoch timestamp to datetime.datetime object."""
    return datetime.datetime.fromtimestamp(int(val))


aiosqlite.register_adapter(datetime, adapt_datetime_epoch)
aiosqlite.register_converter('timestamp', convert_timestamp)


class SqliteStorage(Sql):
    def __init__(self):
        super().__init__()

        server = config.server
        paths: Paths = server.network.paths
        data_dir = \
            f'{paths.root_directory}/{paths.get(Paths.ACCOUNT_DATA_DIR)}'

        self.data_dir = data_dir
        self.account_db_file: str = f'{data_dir}/sqlite.db'

        os.makedirs(data_dir, exist_ok=True)

    async def setup():
        '''
        Factory for SqliteStorage class
        '''

        sqlite = SqliteStorage()

        # async method must be called outside of the SqliteStorage.__init__()
        sqlite.account_db_conn = await aiosqlite.connect(
            sqlite.account_db_file
        )
        sqlite.account_db_conn.row_factory = aiosqlite.Row
        # sqlite.account_db_conn.isolation_level = None

        await sqlite.execute('''
            CREATE TABLE IF NOT EXISTS memberships(member_id, service_id, timestamp, status)
        ''')    # noqa: E501

        return sqlite

    async def setup_member_db(self, member_id: UUID, schema: Schema):
        '''
        Opens the SQLite file for the membership. If the SQLlite file does not
        exist, it will be created and tables will be generated
        '''

        server: Paths = config.server
        paths: Paths = server.network.paths
        member_data_dir = paths.get(
            Paths.MEMBER_DATA_DIR, member_id=member_id
        )

        if member_id not in self.member_db_conns:
            if not os.path.exists(member_data_dir):
                os.makedirs(member_data_dir, exist_ok=True)
                _LOGGER.debug(
                    f'Created member db data directory {member_data_dir}'
                )

        member_data_file = f'{member_data_dir}/sqlite.db'
        member_db_conn = await aiosqlite.connect(member_data_file)
        member_db_conn.row_factory = aiosqlite.Row
        # member_db_conn.isolation_level = None
        self.member_db_conns[member_id] = member_db_conn

        table_defs = self.get_table_definitions(schema.data_classes)
        for table_name in table_defs.keys():
            query = (
                f'CREATE TABLE IF NOT EXISTS {table_name}(' +
                ', '.join(table_defs[table_name].keys()) +
                ')'
            )
            _LOGGER.debug(f'Creating table: {query}')
            await self.execute(query)

    async def _get_tables(self, member_id: UUID = None) -> list[Row]:
        result: aiosqlite.cursor.Cursor = await self.execute(
            r'''
                SELECT name
                FROM sqlite_schema
                WHERE type="table" AND name NOT LIKE "sqlite_%"
            ''',
            member_id
        )
        rows = await result.fetchall()
        _LOGGER.debug(f'Round {len(rows)} tables in account DB')

        return rows

    async def read(self, member: Member):
        '''
        Reads all the data for a membership
        '''

        raise NotImplementedError(
            'No read method implemented for SqliteStorage'
        )

    async def write(self, member: Member):
        '''
        Writes all the data for a membership
        '''

        raise NotImplementedError(
            'No write method implemented for SqliteStorage'
        )

    async def setup_membership(member_id: UUID, schema: Schema):
        raise NotImplementedError
