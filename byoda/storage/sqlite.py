'''
There is both a generic SQL and a AioSqliteStorage class. The generic SQL
class takes care of converting the data schema of a service to a SQL table.
The AioSqliteStorage class takes care of persisting the data.

Each membership of a service gets its own SqlLite DB file under the
root-directory, ie.: /byoda/sqlite/<member_id>.db

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import logging
from uuid import UUID
from typing import TypeVar
from datetime import datetime, timezone

import aiosqlite
from aiosqlite.core import Connection

from byoda.datatypes import MemberStatus
from byoda.datamodel.sqltable import SqlTable
from byoda.datamodel.datafilter import DataFilterSet

from byoda.util.paths import Paths

from byoda import config

Member = TypeVar('Member')
Schema = TypeVar('Schema')

_LOGGER = logging.getLogger(__name__)

# Generic type for SQL cursors. The value will be set by the constructor
# of the class for the specific SQL engine, derived from the SQL class
Cursor: type = None


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

    async def execute(self, command: str, member_id: UUID = None,
                      data: dict[str, str | int | float | bool] = None,
                      autocommit: bool = True, fetchall: bool = False
                      ) -> Cursor:
        '''
        Executes the SQL command.

        :param command: SQL command to execute
        :parm member_id: member_id for the member DB to execute the command on
        :param data: data to use for the named placeholders in the SQL command
        :param autocommit: whether to commit the transaction after executing
        :param fetchall: should rows be fetched and returned
        :returns: if 'fetchall' is False, the Cursor to the result, otherwise
        a list of rows
        '''

        # con = self.connection(member_id)

        if member_id:
            _LOGGER.debug(f'Executing SQL for member {member_id}: {command}')
            db_conn = await aiosqlite.connect(
                self.member_data_files[member_id]
            )
        else:
            _LOGGER.debug(f'Executing SQL for account: {command}')
            db_conn = await aiosqlite.connect(self.account_db_file)

        db_conn.row_factory = aiosqlite.Row

        try:
            if not fetchall:
                result = await db_conn.execute(command, data)
            else:
                result = await db_conn.execute_fetchall(command, data)

            if autocommit:
                _LOGGER.debug(
                    f'Committing transaction for SQL command: {command}'
                )
                await db_conn.commit()
            else:
                _LOGGER.debug(f'Not SQL committing for SQL command {command}')

            await db_conn.close()

            return result
        except aiosqlite.Error as exc:
            await db_conn.rollback()
            await db_conn.close()
            _LOGGER.error(
                f'Error executing SQL: {exc}')

            raise RuntimeError(exc)

    async def query(self, member_id: UUID, key: str,
                    filters: DataFilterSet = None) -> dict[str, object]:
        '''
        Execute the query on the SqlTable for the member_id and key
        '''

        sql_table: SqlTable = self.member_sql_tables[member_id][key]
        return await sql_table.query(filters)

    async def mutate(self, member_id: UUID, key: str, data: dict[str, object],
                     data_filter_set: DataFilterSet = None):
        '''
        Execute the mutation on the SqlTable for the member_id and key
        '''

        sql_table: SqlTable = self.member_sql_tables[member_id][key]
        return await sql_table.mutate(data, data_filter_set)

    async def append(self, member_id: UUID, key: str, data: dict[str, object]):
        '''
        Execute the append on the SqlTable for the member_id and key
        '''

        sql_table: SqlTable = self.member_sql_tables[member_id][key]
        return await sql_table.append(data)

    async def delete(self, member_id: UUID, key: str,
                     data_filter_set: DataFilterSet = None):
        '''
        Execute the delete on the SqlTable for the member_id and key
        '''

        sql_table: SqlTable = self.member_sql_tables[member_id][key]
        return await sql_table.delete(data_filter_set)

    async def read(self, member: Member, class_name: str,
                   filters: DataFilterSet):
        '''
        Reads all the data for a membership
        '''

        return await self.query(member.id, class_name, filters)

    async def write(self, member: Member):
        '''
        Writes all the data for a membership
        '''

        raise NotImplementedError(
            'No write method implemented for AioSqliteStorage'
        )


class SqliteStorage(Sql):
    def __init__(self):
        super().__init__()

        server = config.server
        paths: Paths = server.network.paths
        data_dir = \
            f'{paths.root_directory}/{paths.get(Paths.ACCOUNT_DATA_DIR)}'

        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self.account_db_file: str = f'{data_dir}/sqlite.db'

        self.member_sql_tables: dict[UUID, dict[str, SqlTable]] = {}
        self.member_data_files: dict[UUID, str] = {}

        global Cursor
        Cursor = aiosqlite.Cursor

    async def setup():
        '''
        Factory for SqliteStorage class
        '''

        sqlite = SqliteStorage()

        # async method must be called outside of the SqliteStorage.__init__()
        _LOGGER.debug(
            'Opening or creating account DB file {sqlite.account_db_file}'
        )
        sqlite.account_db_conn = await aiosqlite.connect(
            sqlite.account_db_file
        )
        sqlite.account_db_conn.row_factory = aiosqlite.Row

        await sqlite.execute('''
            CREATE TABLE IF NOT EXISTS memberships(
                member_id TEXT,
                service_id INTEGER,
                timestamp REAL,
                status TEXT
            ) STRICT
        ''')    # noqa: E501

        return sqlite

    async def setup_member_db(self, member_id: UUID, service_id: int,
                              schema: Schema) -> None:
        '''
        Opens the SQLite file for the membership. If the SQLlite file does not
        exist, it will be created and tables will be generated
        '''

        server: Paths = config.server
        paths: Paths = server.network.paths
        member_data_dir = (
            paths.root_directory +
            '/' +
            paths.get(Paths.MEMBER_DATA_DIR, member_id=member_id)
        )

        if not os.path.exists(member_data_dir):
            os.makedirs(member_data_dir, exist_ok=True)
            _LOGGER.debug(
                f'Created member db data directory {member_data_dir}'
            )

        member_data_file = f'{member_data_dir}/sqlite.db'
        # this will create the DB file if it doesn't exist already
        member_db_conn = await aiosqlite.connect(member_data_file)
        member_db_conn.row_factory = aiosqlite.Row

        self.member_db_conns[member_id] = member_db_conn
        self.member_data_files[member_id]: str = member_data_file
        self.member_sql_tables[member_id]: dict[str, SqlTable] = {}

        await self.set_membership_status(
            member_id, service_id, MemberStatus.ACTIVE
        )
        for data_class in schema.data_classes.values():
            # defined_classes are referenced by other classes so we don't
            # have to create tables for them here
            if not data_class.defined_class:
                sql_table = await SqlTable.setup(
                    data_class, self, member_id, schema.data_classes
                )
                self.member_sql_tables[member_id][data_class.name] = sql_table

    async def set_membership_status(self, member_id: UUID, service_id: int,
                                    status: MemberStatus):
        '''
        Sets the status of a membership
        '''

        # Can't use data dict parameter with 'member_id' key as the
        # SqlTable.execute() method will try to update the SQL tables for
        # the membership
        rows = await self.execute(
            (
                'SELECT member_id, service_id, status, timestamp '
                'FROM memberships '
                f'WHERE member_id = "{member_id}" '
                'ORDER BY timestamp DESC '
                'LIMIT 1'
            ),
            fetchall=True
        )

        if len(rows) and rows[0]['status'] == status:
            _LOGGER.debug('No need to change membership status')
            return

        if len(rows) == 0:
            _LOGGER.debug(f'No membership info found for service {service_id}')
        else:
            db_status = rows[0]['status']
            _LOGGER.debug(
                f'Existing status of membership for service {service_id}: '
                f'{db_status}'
            )

        await self.execute(
            (
                'INSERT INTO memberships '
                '(member_id, service_id, status, timestamp) '
                'VALUES ('
                f'    "{member_id}", :service_id, :status, :timestamp)'
            ),
            data={
                'service_id': service_id,
                'status': status.value,
                'timestamp': datetime.now(tz=timezone.utc).timestamp()
            }
        )

    async def get_memberships(self, status: MemberStatus = MemberStatus.ACTIVE
                              ) -> dict[str, object]:
        '''
        Get the latest status of all memberships

        :param status: The status of the membership to return. If 'None' is
        set, the latest membership status for all memberships will be
        returned
        '''

        rows = await self.execute(
            (
                'SELECT member_id, service_id, status, timestamp '
                'FROM memberships '
                'ORDER BY timestamp ASC '
                'LIMIT 1'
            ),
            fetchall=True
        )

        memberships: dict[str, object] = {}
        for row in rows:
            member_id = UUID(row['member_id'])
            memberships[member_id] = {
                'member_id': member_id,
                'service_id': int(row['service_id']),
                'status': row['status'],
                'timestamp': row['timestamp'],
            }

        memberships_status = {
            key: value for key, value in memberships.items()
            if status is None or value['status'] == status.value
        }

        return memberships_status


class AioSqliteStorage(Sql):
    def __init__(self):
        super().__init__()

        server = config.server
        paths: Paths = server.network.paths
        data_dir = \
            f'{paths.root_directory}/{paths.get(Paths.ACCOUNT_DATA_DIR)}'

        self.data_dir = data_dir
        self.account_db_file: str = f'{data_dir}/sqlite.db'

        self.member_sql_tables: dict[str, dict[str, SqlTable]] = {}

        os.makedirs(data_dir, exist_ok=True)

        global Cursor
        Cursor = aiosqlite.Cursor

    async def setup():
        '''
        Factory for AioSqliteStorage class
        '''

        sqlite = AioSqliteStorage()

        # async method must be called outside of the
        # AioSqliteStorage.__init__()
        _LOGGER.debug(
            'Opening or creating account DB file {sqlite.account_db_file}'
        )
        sqlite.account_db_conn = await aiosqlite.connect(
            sqlite.account_db_file
        )
        sqlite.account_db_conn.row_factory = aiosqlite.Row

        await sqlite.execute('''
            CREATE TABLE IF NOT EXISTS memberships(
                member_id TEXT,
                service_id INTEGER,
                timestamp REAL,
                status TEXT
            ) STRICT
        ''')    # noqa: E501

        return sqlite

    async def setup_member_db(self, member_id: UUID, service_id: int,
                              schema: Schema) -> None:
        '''
        Opens the SQLite file for the membership. If the SQLlite file does not
        exist, it will be created and tables will be generated
        '''

        server: Paths = config.server
        paths: Paths = server.network.paths
        member_data_dir = (
            paths.root_directory +
            '/' +
            paths.get(Paths.MEMBER_DATA_DIR, member_id=member_id)
        )

        if not os.path.exists(member_data_dir):
            os.makedirs(member_data_dir, exist_ok=True)
            _LOGGER.debug(
                f'Created member db data directory {member_data_dir}'
            )

        member_data_file = f'{member_data_dir}/sqlite.db'
        # this will create the DB file if it doesn't exist already
        member_db_conn = await aiosqlite.connect(member_data_file)
        member_db_conn.row_factory = aiosqlite.Row

        self.member_db_conns[member_id] = member_db_conn
        self.member_sql_tables[member_id]: dict[str, SqlTable] = {}

        await self.set_membership_status(
            member_id, service_id, MemberStatus.ACTIVE
        )
        for data_class in schema.data_classes.values():
            # defined_classes are referenced by other classes so we don't
            # have to create tables for them here
            if not data_class.defined_class:
                sql_table = await SqlTable.setup(
                    data_class, self, member_id, schema.data_classes
                )
                self.member_sql_tables[member_id][data_class.name] = sql_table

        await self.set_membership_status(
            member_id, service_id, MemberStatus.ACTIVE
        )

    async def set_membership_status(self, member_id: UUID, service_id: int,
                                    status: MemberStatus):
        '''
        Sets the status of a membership
        '''

        # Can't use data dict parameter with 'member_id' key as the
        # SqlTable.execute() method will try to update the SQL tables for
        # the membership
        rows = await self.execute(
            (
                'SELECT member_id, service_id, status, timestamp '
                'FROM memberships '
                f'WHERE member_id = "{member_id}" '
                'ORDER BY timestamp DESC '
                'LIMIT 1'
            ),
            fetchall=True
        )

        if len(rows) and rows[0]['status'] == status:
            _LOGGER.debug('No need to change membership status')
            return

        if len(rows) == 0:
            _LOGGER.debug(f'No membership info found for service {service_id}')
        else:
            db_status = rows[0]['status']
            _LOGGER.debug(
                f'Existing status of membership for service {service_id}: '
                f'{db_status}'
            )

        await self.execute(
            (
                'INSERT INTO memberships '
                '(member_id, service_id, status, timestamp) '
                'VALUES ('
                f'    "{member_id}", :service_id, :status, :timestamp)'
            ),
            data={
                'service_id': service_id,
                'status': status.value,
                'timestamp': datetime.now(tz=timezone.utc).timestamp()
            }
        )

    async def get_memberships(self, status: MemberStatus = MemberStatus.ACTIVE
                              ) -> dict[str, object]:
        '''
        Get the latest status of all memberships

        :param status: The status of the membership to return. If 'None' is
        set, the latest membership status for all memberships will be
        returned
        '''

        rows = await self.execute(
            (
                'SELECT member_id, service_id, status, timestamp '
                'FROM memberships '
                'ORDER BY timestamp ASC '
                'LIMIT 1'
            ),
            fetchall=True
        )

        memberships: dict[str, object] = {}
        for row in rows:
            member_id = UUID(row['member_id'])
            memberships[member_id] = {
                'member_id': member_id,
                'service_id': int(row['service_id']),
                'status': row['status'],
                'timestamp': row['timestamp'],
            }

        memberships_status = {
            key: value for key, value in memberships.items()
            if status is None or value['status'] == status.value
        }

        return memberships_status
