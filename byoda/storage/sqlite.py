'''
There is both a generic SQL and a SqliteStorage class. The generic SQL
class takes care of converting the data schema of a service to a SQL table.
The SqliteStorage class takes care of persisting the data.

Each membership of a service gets its own SqlLite DB file under the
root-directory, ie.: /byoda/sqlite/<member_id>.db

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import shutil

from uuid import UUID
from typing import TypeVar
from logging import getLogger
from datetime import datetime
from datetime import timezone

import aiosqlite

from byoda.datamodel.sqltable import SqlTable
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.dataclass import SchemaDataObject

from byoda.datatypes import MemberStatus
from byoda.datatypes import CloudType
from byoda.datatypes import MemberInfo

from byoda.secrets.data_secret import DataSecret

from byoda.util.paths import Paths

from byoda.util.logger import Logger

from byoda import config

from .sqlstorage import Sql

Network = TypeVar('Network')
Account = TypeVar('Account')
Member = TypeVar('Member')
Schema = TypeVar('Schema')
PodServer = TypeVar('PodServer')
DocumentStore = TypeVar('DocumentStore')
DataStore = TypeVar('DataStore')
FileStorage = TypeVar('FileStorage')

_LOGGER: Logger = getLogger(__name__)

BACKUP_FILE_EXTENSION: str = '.backup'
PROTECTED_FILE_EXTENSION: str = '.protected'


class SqliteStorage(Sql):
    def __init__(self, paths: Paths):
        super().__init__()

        self.paths: Paths = paths
        self.data_dir: str = (
            self.paths.root_directory + '/' +
            self.paths.get(Paths.ACCOUNT_DATA_DIR)
        )
        os.makedirs(self.data_dir, exist_ok=True)

        self.account_db_file: str = f'{self.data_dir}/account.db'

        self.member_sql_tables: dict[UUID, dict[str, SqlTable]] = {}
        self.member_db_files: dict[UUID, str] = {}

    async def setup(server: PodServer, data_secret: DataSecret | None):
        '''
        Factory for SqliteStorage class. This method restores the account DB
        and membership DBs from the cloud if no local copy exists, except if
        we are not running in the cloud

        :param server: PodServer instance
        :param data_secret: secret to decrypt the protected shared key used
        to encrypt backups of the Sqlite3 DB files
        '''

        paths: Paths = server.paths
        sqlite = SqliteStorage(paths)

        _LOGGER.debug(
            f'Setting up SqliteStorage for cloud {server.cloud.value}'
        )

        if await server.local_storage.exists(sqlite.account_db_file):
            _LOGGER.debug('Local account DB file exists')
        elif data_secret is None:
            raise ValueError(
                'No local account DB exists but no data secret specified'
            )
        else:
            if server.cloud == CloudType.LOCAL:
                _LOGGER.debug(
                    'Not checking for backup as we are not in the cloud'
                )
                await sqlite._create_account_db()
            else:
                if await sqlite._prep_account_db_file(
                        server, data_secret):
                    await sqlite.restore_member_db_files(server)
        _LOGGER.debug(
            f'Using account DB file {sqlite.account_db_file}'
        )

        return sqlite

    async def _prep_account_db_file(self, server: PodServer,
                                    data_secret: DataSecret) -> bool:
        '''
        Downloads the Account DB from the cloud if it exists, otherwise
        creates a new Account DB

        :param server: PodServer instance
        :param data_secret: secret to decrypt the protected shared key used
        to encrypt backups of the Sqlite3 DB files
        :returns: True if the account DB file was restored from the cloud
        '''

        _LOGGER.debug('Account DB file does not exist locally')
        doc_store: DocumentStore = server.document_store
        cloud_file_store: FileStorage = doc_store.backend

        cloud_filepath = (
            self.paths.get(Paths.ACCOUNT_DATA_DIR) + '/' +
            os.path.basename(self.account_db_file) +
            PROTECTED_FILE_EXTENSION
        )

        if await cloud_file_store.exists(cloud_filepath):
            _LOGGER.info(
                f'Restoring account DB file {cloud_filepath} from '
                'cloud'
            )
            await self.restore_db_file(
                cloud_filepath, self.account_db_file,
                cloud_file_store, data_secret
            )
            return True
        else:
            if (server.bootstrapping):
                _LOGGER.debug(
                    f'Protected backup file {cloud_filepath} does not '
                    f'exist in cloud {server.cloud.value}, will create '
                    'new account DB'
                )
                await self._create_account_db()
                return False
            else:
                raise RuntimeError(
                    'No account DB file found on local file system '
                    'and we are not bootstrapping'
                )

    async def _create_account_db(self):
        '''
        Creates the Account DB file and sets the journal mode to WAL
        '''

        await self.execute('''
            CREATE TABLE IF NOT EXISTS memberships(
                member_id TEXT,
                service_id INTEGER,
                timestamp REAL,
                status TEXT
            ) STRICT
        ''')    # noqa: E501
        await self.execute('PRAGMA journal_mode=WAL')
        _LOGGER.debug(f'Created Account DB {self.account_db_file}')

    async def close(self):
        '''
        This is a empty method as we do not maintain any open connections
        for Sqlite3
        '''

        pass

    async def backup_datastore(self, server: PodServer):
        '''
        Backs up the account DB and the membership DB files
        to the cloud. If a DB file has not changed since
        the last backup, it will not be uploaded to the cloud

        :raises: ValueError if the server is running locally
        '''

        if server.cloud == CloudType.LOCAL:
            raise ValueError('Cannot backup to local storage')

        data_secret: DataSecret = server.account.data_secret

        data_store: DataStore = server.data_store
        cloud_file_store: FileStorage = server.document_store.backend

        # First we back up the account DB
        try:
            local_file: str = data_store.backend.account_db_file
            cloud_filepath = (
                self.paths.get(Paths.ACCOUNT_DATA_DIR) + '/' +
                os.path.basename(data_store.backend.account_db_file)
            )
            await self.backup_db_file(
                local_file, cloud_filepath, cloud_file_store, data_secret
            )
        except FileNotFoundError:
            _LOGGER.debug(
                'Not backing up account DB as local file does not exist: '
                f'{local_file}'
            )

        await self.backup_member_db_files(server, data_secret)

    async def backup_member_db_files(self, server: PodServer,
                                     data_secret: DataSecret):
        '''
        Backs up the database files for all memberships
        '''

        cloud_file_store: FileStorage = server.document_store.backend

        memberships: dict[str, MemberInfo] = await self.get_memberships()
        _LOGGER.debug(f'Backing up {len (memberships)} membership DB files')

        for membership in memberships.values():
            cloud_member_data_file = self.get_member_data_filepath(
                membership.member_id, membership.service_id,
                server.paths, local=False
            )
            local_member_data_file = self.get_member_data_filepath(
                membership.member_id, membership.service_id,
                server.paths, local=True
            )

            try:
                await self.backup_db_file(
                    local_member_data_file, cloud_member_data_file,
                    cloud_file_store, data_secret
                )
            except FileNotFoundError:
                _LOGGER.warning(
                    f'Did not find local data file {cloud_member_data_file}'
                )

    async def backup_db_file(self, local_file: str, cloud_file: str,
                             cloud_file_store: FileStorage,
                             data_secret: DataSecret):
        '''
        Backs up the database file to the cloud, if the local file
        is newer than any existing local backup of the file

        :raises: FileNotFoundError if the local file does not exist
        '''

        backup_file = f'{local_file}{BACKUP_FILE_EXTENSION}'
        protected_local_backup_file = \
            f'{backup_file}{PROTECTED_FILE_EXTENSION}'

        _LOGGER.debug(f'Backing up {local_file} to {cloud_file}')

        if not os.path.exists(local_file):
            raise FileNotFoundError(
                f'Can not backup {local_file} as it does not exist'
            )

        if os.path.exists(backup_file):
            file_time = os.path.getmtime(local_file)
            backup_time = os.path.getmtime(backup_file)
            if file_time <= backup_time:
                _LOGGER.debug(
                    f'Not backing up {local_file} as it has not changed: '
                    f'{file_time} <= {backup_time}'
                )
                return

        # If conn paraneter is not passed, we open a new connection
        # and we'll close it as well.
        local_conn = await aiosqlite.connect(local_file)
        backup_conn = await aiosqlite.connect(backup_file)
        await local_conn.execute('pragma synchronous = normal')
        await backup_conn.execute('pragma synchronous = normal')

        try:
            await local_conn.backup(backup_conn)
            await backup_conn.execute('PRAGMA wal_checkpoint(FULL)')
            _LOGGER.debug(f'Successfully created backup of {backup_file}')
        except Exception:
            _LOGGER.exception('Failed to backup database')

        await backup_conn.close()
        await local_conn.close()

        data_secret.encrypt_file(backup_file, protected_local_backup_file)

        with open(protected_local_backup_file, 'rb') as file_desc:
            cloud_file += PROTECTED_FILE_EXTENSION
            await cloud_file_store.write(cloud_file, file_descriptor=file_desc)
            _LOGGER.debug(f'Saved backup to cloud: {cloud_file}')

        os.remove(protected_local_backup_file)

    async def restore_member_db_files(self, server: PodServer):
        '''
        Downloads all the member DB files from the cloud
        '''

        paths: Paths = server.paths
        account_data_secret: DataSecret = server.account.data_secret
        doc_store: DocumentStore = server.document_store
        cloud_file_store: FileStorage = doc_store.backend

        memberships: dict[str, MemberInfo] = await self.get_memberships()
        for membership in memberships.values():
            service_id = membership.service_id
            member_id: UUID = membership.member_id
            cloud_member_data_file = self.get_member_data_filepath(
                member_id, service_id, paths,
                local=False
            )
            cloud_member_data_file += PROTECTED_FILE_EXTENSION

            local_member_data_file = self.get_member_data_filepath(
                member_id, service_id, paths, local=True
            )

            try:
                await self.restore_db_file(
                    cloud_member_data_file, local_member_data_file,
                    cloud_file_store, account_data_secret
                )
            except FileNotFoundError:
                _LOGGER.warning(
                    f'Did not find cloud data file {cloud_member_data_file}'
                )

    async def restore_db_file(self, cloud_file: str, local_file: str,
                              cloud_file_store: FileStorage,
                              account_data_secret: DataSecret):
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

        protected_file = local_file + PROTECTED_FILE_EXTENSION
        with open(protected_file, 'wb') as file_desc:
            file_desc.write(data)

        # Create a backup locally as it will prevent the unmodified
        # database from being backed up to the cloud
        backup_file = local_file + BACKUP_FILE_EXTENSION
        account_data_secret.decrypt_file(protected_file, backup_file)

        # Only now create the database file so it will not be
        # newer than the backup file
        _LOGGER.debug(f'Copying {backup_file} to {local_file}')
        shutil.copy2(backup_file, local_file)

        _LOGGER.debug(f'Deleting downloaded protected file {protected_file}')
        os.remove(protected_file)

    async def setup_member_db(self, member_id: UUID, service_id: int) -> None:
        '''
        Opens the SQLite file for the membership. If the SQLlite file does not
        exist, it will be created and tables will be generated
        '''

        _LOGGER.debug(f'Setting up member DB for member {member_id}')

        server: Paths = config.server
        paths: Paths = server.network.paths
        member_db_file = self.get_member_data_filepath(
            member_id, service_id, paths, local=True
        )

        member_data_dir = os.path.dirname(member_db_file)

        if not os.path.exists(member_data_dir):
            os.makedirs(member_data_dir, exist_ok=True)
            _LOGGER.debug(
                f'Created member db data directory {member_data_dir}'
            )

        self.member_db_files[member_id]: str = member_db_file
        self.member_sql_tables[member_id]: dict[str, SqlTable] = {}

        # this will create the DB file if it doesn't exist already
        async with aiosqlite.connect(member_db_file) as db_conn:
            # This ensures that the Sqlite3 DB uses WAL
            await db_conn.execute('PRAGMA journal_mode = WAL')

        await self.set_membership_status(
            member_id, service_id, MemberStatus.ACTIVE
        )

    async def create_table(self, member_id,
                           data_class: SchemaDataArray | SchemaDataObject,
                           ) -> SqlTable:
        '''
        Creates a table for a data class in the schema of a membershipin in
        the Sqlite3 database for the membership

        :param member_id:
        :param data_class: data class to create the table for
        :param data_classes: list of data classes in the schema of the service
        :returns: the created table
        '''

        sql_table = await SqlTable.setup(data_class, self, member_id)

        return sql_table

    def add_sql_table(self, member_id: UUID, class_name: str,
                      sql_table: SqlTable) -> None:
        '''
        Adds the SQL table to the list of tables we have created for the
        membership
        '''

        _LOGGER.debug(f'Adding table {class_name} for member {member_id}')
        self.member_sql_tables[member_id][class_name] = sql_table

    def get_sql_table(self, member_id: UUID, class_name: str
                      ) -> SqlTable | None:
        '''
        Returns the SQL table for the membership if it exists
        '''

        return self.member_sql_tables[member_id].get(class_name)

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
                              ) -> dict[UUID, MemberInfo]:
        '''
        Get the latest status of all memberships

        :param status: The status of the membership to return. If its value is
        'None' the latest membership status for all memberships will be. If the
        status parameter has a value, only the memberships with that status are
        returned
        :returns: a dict with the latest membership status for each membership,
        keyed with the member ID
        '''

        query = (
            'SELECT member_id, service_id, status, timestamp '
            'FROM memberships '
        )
        if status:
            query += f'WHERE status = "{status.value}" '

        if not os.path.exists(self.account_db_file):
            return {}

        rows = await self.execute(query, fetchall=True)

        memberships: dict[str, object] = {}
        for row in rows:
            try:
                member_id = UUID(row['member_id'])
                membership = MemberInfo(
                    member_id=member_id,
                    service_id=int(row['service_id']),
                    status=MemberStatus(row['status']),
                    timestamp=float(row['timestamp']),
                )
                if status or member_id not in memberships:
                    memberships[member_id] = membership
                else:
                    existing_membership: MemberInfo = memberships[member_id]
                    existing_timestamp = existing_membership.timestamp
                    if membership.timestamp >= existing_timestamp:
                        memberships[member_id] = membership
            except ValueError as exc:
                _LOGGER.warning(
                    f'Row with invalid data in account DB: {exc}'
                )

        memberships_for_status: dict[str, MemberInfo] = {
            key: value for key, value in memberships.items()
            if status is None or value.status == status
        }

        _LOGGER.debug(
            f'Found {len(memberships_for_status)} memberships '
            'in Sqlite Account DB'
        )

        return memberships_for_status

    async def maintain(self, server: PodServer):
        '''
        Performs maintenance on the membership Sqlite DB files.
        '''

        memberships: dict[str, MemberInfo] = await self.get_memberships()
        _LOGGER.debug(
            f'Performing Sqlit3 DB maintenance on {len(memberships)} DB files'
        )

        for membership in memberships.values():
            member_data_file = self.get_member_data_filepath(
                membership.member_id, membership.service_id,
                server.paths, local=True
            )

            try:
                async with aiosqlite.connect(member_data_file) as db_conn:
                    await db_conn.execute('PRAGMA wal_checkpoint(FULL)')
                    _LOGGER.debug(
                        f'Finished WAL checkpointing on {member_data_file}'
                    )
            except Exception as exc:
                _LOGGER.warning(
                    'Could not checkpoint Sqlite3 DB file '
                    f'{member_data_file}: {exc}'
                )
