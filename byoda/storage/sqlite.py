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
from typing import TypeVar
from datetime import datetime, timezone

import aiosqlite
from aiosqlite.core import Connection

from byoda.datatypes import MemberStatus
from byoda.datatypes import CloudType
from byoda.datamodel.sqltable import SqlTable
from byoda.datamodel.datafilter import DataFilterSet

from byoda.util.paths import Paths

from byoda import config

Member = TypeVar('Member')
Schema = TypeVar('Schema')
PodServer = TypeVar('PodServer')
DocumentStore = TypeVar('DocumentStore')
DataStore = TypeVar('DataStore')
FileStorage = TypeVar('FileStorage')

_LOGGER = logging.getLogger(__name__)

BACKUP_FILE_EXTENSION: str = '.backup'

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
            _LOGGER.debug(
                f'Executing SQL for member {member_id}: {command} using '
                f'SQL data file {self.member_data_files[member_id]}'
            )
            db_conn = await aiosqlite.connect(
                self.member_data_files[member_id]
            )
        else:
            _LOGGER.debug(
                f'Executing SQL for account: {command} using '
                f'SQL data file {self.account_db_conn}'
            )
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
                     data_filter_set: DataFilterSet = None) -> int:
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
                     data_filter_set: DataFilterSet = None) -> int:
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
            'No write method implemented for Sql storage'
        )


class SqliteStorage(Sql):
    def __init__(self):
        super().__init__()

        server = config.server
        self.paths: Paths = server.network.paths
        data_dir = (
            self.paths.root_directory + '/' +
            self.paths.get(Paths.ACCOUNT_DATA_DIR)
        )
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self.account_db_file: str = f'{data_dir}/account.db'

        self.member_sql_tables: dict[UUID, dict[str, SqlTable]] = {}
        self.member_data_files: dict[UUID, str] = {}

        global Cursor
        Cursor = aiosqlite.Cursor

    async def setup(server: PodServer):
        '''
        Factory for SqliteStorage class
        '''

        sqlite = SqliteStorage()

        db_downloaded: bool = False
        if (server.cloud != CloudType.LOCAL
                and
                not await server.local_storage.exists(sqlite.account_db_file)):
            db_downloaded = True

            doc_store: DocumentStore = server.document_store

            cloud_file_store: FileStorage = doc_store.backend

            cloud_filepath = (
                sqlite.paths.get(Paths.ACCOUNT_DATA_DIR) + '/' +
                os.path.basename(sqlite.account_db_file)
            )
            if await cloud_file_store.exists(cloud_filepath):
                sqlite.restore_db_file(
                    sqlite.account_db_cfile, cloud_filepath, cloud_file_store
                )

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

        if db_downloaded:
            await sqlite.restore_member_db_files(server)

        return sqlite

    async def close(self):
        '''
        Close all connections to Sqlite files. This method must
        be called upon shutdown of the server as otherwise the
        'asyncio' event loop will not exit
        '''

        await self.account_db_conn.close()

        for conn in self.member_db_conns.values():
            await conn.close()

    async def backup(self, server: PodServer):
        '''
        Backs up the account DB and the membership DB files
        to the cloud. If a DB file has not changed since
        the last backup, it will not be uploaded to the cloud

        :raises: ValueError if the server is running locally
        '''

        if server.cloud == CloudType.LOCAL:
            raise ValueError('Cannot backup to local cloud')

        data_store: DataStore = server.data_store
        cloud_file_store: FileStorage = server.doc_store.backend

        # First we back up the account DB
        try:
            local_file: str = data_store.backend.account_db_file
            cloud_filepath = (
                self.paths.get(Paths.ACCOUNT_DATA_DIR) + '/' +
                os.path.basename(data_store.backend.account_db_file)
            )
            await self.backup_db_file(
                local_file, cloud_filepath, cloud_file_store,
                self.account_db_conn
            )
        except PermissionError:
            _LOGGER.debug(
                f'Not restoring account DB as local copy exists: {local_file}'
            )

    async def backup_member_db_files(self, server: PodServer):
        '''
        Backs up the database files for all memberships
        '''

        cloud_file_store: FileStorage = server.doc_store.backend

        memberships: list[dict[str, object]] = await self.get_memberships()
        for membership in memberships.values():
            cloud_member_data_file = self.get_member_data_filepath(
                membership['member_id'], membership['service_id'],
                server.paths, local=False
            )
            local_member_data_file = self.get_member_data_filepath(
                membership['member_id'], membership['service_id'],
                server.paths, local=True
            )

            try:
                self.backup_db_file(
                    local_member_data_file,
                    cloud_member_data_file,
                    cloud_file_store,
                    self.member_db_conns[membership['member_id']]
                )
            except FileNotFoundError:
                _LOGGER.warning(
                    f'Did not find local data file {cloud_member_data_file}'
                )

    async def backup_db_file(self, local_file: str, cloud_file: str,
                             cloud_file_store: FileStorage,
                             conn: aiosqlite.Connection):
        '''
        Backs up the database file to the cloud, if the local file
        is newer than any existing local backup of the file

        :raises: FileNotFoundError if the local file does not exist
        '''

        backup_file = f'{local_file}{BACKUP_FILE_EXTENSION}'

        if not os.path.exists(local_file):
            raise FileNotFoundError(
                f'Can not backup {local_file} as it does not exist'
            )

        if os.path.exists(backup_file):
            file_time = os.path.getmtime(local_file)
            backup_time = os.path.getmtime(backup_file)
            if file_time <= backup_time:
                _LOGGER.debug(
                    f'Not backing up {local_file} as it has not changed'
                )
            return

        backup_conn = await aiosqlite.connect(backup_file)
        await conn.backup(backup_conn)
        await backup_conn.close()
        with open(backup_file, 'rb') as file_desc:
            cloud_file_store.write(cloud_file, file_descriptor=file_desc)

    async def restore_db_file(self, local_file: str, cloud_file: str,
                              cloud_file_store: FileStorage):
        '''
        Restores the a database file from the cloud

        :raises: PermissionError if the local file already exists,
        FileNotFound if the file does not exist in the cloud
        '''

        if os.path.exists(local_file):
            raise PermissionError(
                f'Not restoring {local_file} as it already exists'
            )

        _LOGGER.debug(f'Restoring {cloud_file}')

        os.makedirs(
            os.path.dirname(local_file), exist_ok=True
        )

        _LOGGER.debug(f'Restoring database from cloud: {local_file}')

        # TODO: create non-blocking copy from cloud to local in FileStorage()
        data = await cloud_file_store.read(cloud_file)

        # Create a backup locally as it will prevent the unmodified
        # database from being backed up to the cloud
        backup_file = local_file + BACKUP_FILE_EXTENSION
        with open(backup_file, 'wb') as file_desc:
            file_desc.write(data)

        # Only now create the database file so it will not be
        # newer than the backup file
        with open(local_file, 'wb') as file_desc:
            file_desc.write(data)

    async def restore_member_db_files(self, server: PodServer):
        '''
        Downloads all the member DB files from the cloud
        '''

        doc_store: DocumentStore = server.document_store

        paths: Paths = server.paths

        cloud_file_store: FileStorage = doc_store.backend

        memberships: list[dict[str, object]] = await self.get_memberships()
        for membership in memberships.values():
            cloud_member_data_file = self.get_member_data_filepath(
                membership['member_id'], membership['service_id'], paths,
                local=False
            )
            local_member_data_file = self.get_member_data_filepath(
                membership['member_id'], membership['service_id'], paths,
                local=True
            )

            try:
                self.restore_db_file(
                    local_member_data_file, cloud_member_data_file,
                    cloud_file_store
                )
            except FileNotFoundError:
                _LOGGER.warning(
                    f'Did not find cloud data file {cloud_member_data_file}'
                )

    async def setup_member_db(self, member_id: UUID, service_id: int,
                              schema: Schema) -> None:
        '''
        Opens the SQLite file for the membership. If the SQLlite file does not
        exist, it will be created and tables will be generated
        '''

        server: Paths = config.server
        paths: Paths = server.network.paths
        member_data_file = self.get_member_data_filepath(
            member_id, service_id, paths, local=True)

        member_data_dir = os.path.dirname(member_data_file)

        if not os.path.exists(member_data_dir):
            os.makedirs(member_data_dir, exist_ok=True)
            _LOGGER.debug(
                f'Created member db data directory {member_data_dir}'
            )

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

    def get_member_data_filepath(self, member_id: UUID, service_id: int,
                                 paths: Paths = None, local: bool = True
                                 ) -> str:
        '''
        Returns the filepath for the member data file

        :param member_id: The member ID
        :param service_id: The service ID
        :param paths: The Paths object, if None then the path to the file will
        not be included in the returned result
        :param local: should we return a relative path or an absolute path.
        The latter can be used when using the local file system.
        :returns: file name (optionally including the full path to it)
        '''

        path = ''
        if paths:
            if local:
                path = paths.root_directory + '/'

            path += paths.get(Paths.MEMBER_DATA_DIR, member_id=member_id) + '/'

        path += paths.get(
            Paths.MEMBER_DATA_FILE, member_id=member_id, service_id=service_id
        )

        return path

    async def set_membership_status(self, member_id: UUID, service_id: int,
                                    status: MemberStatus):
        '''
        Sets the status of a membership
        '''

        # Can't use data dict parameter with 'member_id' key as the
        # SqlTable.execute() method will try to update the SQL tables for
        # the membership if a member_id parameter is specified.
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

        if len(rows) and rows[0]['status'] == status.value:
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

        :param status: The status of the membership to return. If its value is
        'None' the latest membership status for all memberships will be. If the
        status parameter has a value, only the memberships with that status are
        returned
        '''

        query = (
            'SELECT member_id, service_id, status, timestamp '
            'FROM memberships '
        )
        if status:
            query += f'WHERE status = "{status.value}" '

        rows = await self.execute(query, fetchall=True)

        memberships: dict[str, object] = {}
        for row in rows:
            try:
                member_id = UUID(row['member_id'])
                membership: dict[str, UUID | int | MemberStatus | float] = {
                    'member_id': member_id,
                    'service_id': int(row['service_id']),
                    'status': MemberStatus(row['status']),
                    'timestamp': float(row['timestamp']),
                }
                if status or member_id not in memberships:
                    memberships[member_id] = membership
                else:
                    existing_timestamp = memberships[member_id]['timestamp']
                    if membership['timestamp'] >= existing_timestamp:
                        memberships[member_id] = membership
            except ValueError as exc:
                _LOGGER.warning(
                    f'Row with invalid data in account DB: {exc}'
                )

        memberships_status = {
            key: value for key, value in memberships.items()
            if status is None or value['status'] == status
        }

        _LOGGER.debug(
            f'Found {len(memberships_status)} memberships '
            'in Sqlite Account DB'
        )

        return memberships_status
