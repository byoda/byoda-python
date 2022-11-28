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

import aiosqlite

from byoda import config

from byoda.util.paths import Paths

Member = TypeVar('Member')
Schema = TypeVar('Schema')

_LOGGER = logging.getLogger(__name__)


class Sql:
    GET_QUERY = None
    APPEND_QUERY = None
    UPDATE_QUERY = None
    DELETE_QUERY = None

    def __init__(self):
        self.account_db_conn: aiosqlite.core.Connection | None = None

        self.member_db_conns: dict[str, aiosqlite.core.Connection] = {}

    @property
    def get_query(self):
        return self.GET_QUERY

    @get_query.setter
    def set_query(self, query: str):
        self.GET_QUERY = query

    @property
    def update_query(self):
        return self.UPDATE_QUERY

    @update_query.setter
    def update_query(self, query: str):
        self.UPDATE_QUERY = query

    @property
    def append_query(self):
        return self.APPEND_QUERY

    @append_query.setter
    def append_query(self, query: str):
        self.APPEND_QUERY = query

    @property
    def delete_query(self):
        return self.DELETE_QUERY

    @delete_query.setter
    def delete_query(self, query: str):
        self.DELETE_QUERY = query

    def connection(self, member_id: UUID = None) -> aiosqlite.core.Connection:
        if not member_id:
            con: aiosqlite.core.Connection = self.account_db_conn
            _LOGGER.debug('Using account DB connection')
        else:
            con: aiosqlite.core.Connection = self.member_db_conns.get(
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

    async def execute(self, command: str, member_id: UUID = None) -> list[Row]:
        con = self.connection(member_id)
        result = await con.execute(command)
        return result


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

        rows = await sqlite._get_tables()
        if 'memberships' not in rows:
            await sqlite.execute('''
                CREATE TABLE memberships(member_id, service_id, timestamp, status)
            ''')    # noqa: E501
            _LOGGER.debug('Creating memberships table in account DB')
        return sqlite

    async def setup_member_db(self, member: Member):
        '''
        Opens the SQLite file for the membership. If the SQLlite file does not
        exist, it will be created and tables will be generated
        '''

        server: Paths = config.server
        paths: Paths = server.paths
        member_data_dir = paths.get(
            Paths.MEMBER_DATA_DIR, member_id=member.member_id
        )

        if member.member_id not in self.member_db_conns:
            if not os.path.exists(member_data_dir):
                _LOGGER.debug(
                    f'Created member db data directory {member_data_dir}'
                )
                os.makedirs(member_data_dir, exist_ok=True)

        member_data_file = f'{member_data_dir}/sqlite.db'
        member_db = await aiosqlite.connect(member_data_file)

        self.member_db_conns[member.member_id] = member_db

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
