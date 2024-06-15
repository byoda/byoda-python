'''
There is both a generic SQL and a SqliteStorage class. The generic SQL
class takes care of converting the data schema of a service to a SQL table.
The SqliteStorage class takes care of persisting the data.

Each membership of a service gets its own SqlLite DB file under the
root-directory, ie.: /byoda/sqlite/<member_id>.db

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

# flake8: noqa: E402

import os
import shutil
import subprocess

from uuid import UUID
from typing import Self, Tuple
from typing import TypeVar
from typing import override
from logging import getLogger

import orjson

os.environ['PSYCOPG_IMPL'] = 'binary'
from psycopg import connect
from psycopg import Connection
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from psycopg import Cursor

from psycopg import AsyncCursor
from psycopg.errors import CheckViolation
from psycopg.errors import UniqueViolation
from psycopg.errors import SyntaxError
from psycopg.errors import InvalidCatalogName
from psycopg.errors import DuplicateDatabase
from psycopg.errors import DuplicateObject
from psycopg.errors import ObjectInUse
from psycopg.errors import OperationalError

from psycopg.types.json import set_json_dumps
from psycopg.types.json import set_json_loads

from byoda.datatypes import DataType
from byoda.datatypes import CloudType
from byoda.datatypes import AnyScalarType

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

DB_NAME: str = 'byoda'

BACKUP_FILE: str = 'backup.dump'
PROTECTED_FILE_EXTENSION: str = '.prot'


class PostgresStorage(Sql):
    @override
    def __init__(self, connection_string: str, paths: Paths,
                 data_secret: DataSecret | None) -> None:
        super().__init__()

        self.connection_string: str = connection_string
        self.pool: AsyncConnectionPool | None = None

        self.paths: Paths = paths
        self.data_secret: DataSecret = data_secret

        set_json_dumps(orjson.dumps)
        set_json_loads(orjson.loads)

    async def setup(connection_string: str, server: PodServer,
                    ) -> Self:
        '''
        Factory for PostgresStorage class

        :param connection_string: postgres connecting string WITHOUT the
        specification of the database to use
        :param server: PodServer instance
        '''

        log_data: dict[str, any] = {
            'connection_string': connection_string,
        }
        _LOGGER.info(f'Connecting to Postgres', extra=log_data)

        conn: Connection[Tuple] | None = None
        restore_backup_needed: bool = False
        try:
            conn: Connection[Tuple] = connect(
                f'{connection_string}/byoda', autocommit=True
            )
        except OperationalError as exc:
            log_data['exception'] = exc
            _LOGGER.info(
                'Could not open the database or restore it from backup',
                extra=log_data
            )
            del log_data['exception']
            restore_backup_needed = True

        new_db_needed: bool = False
        if restore_backup_needed:
            if server.cloud == CloudType.LOCAL:
                new_db_needed = True
            else:
                try:
                    await PostgresStorage.restore_backup(connection_string, server)
                    conn: Connection[Tuple] = connect(
                        f'{connection_string}/byoda', autocommit=True
                    )
                    conn.close()
                    restore_backup_needed = False
                except OperationalError:
                    new_db_needed = True

        if new_db_needed:
            _LOGGER.info(
                f'Could not restore the database {connection_string} '
                'from the cloud, creating a new database instead.'
            )
            PostgresStorage._create_database(connection_string)

        account: Account = server.account
        self = PostgresStorage(
            connection_string, account.paths, account.data_secret
        )

        self.pool = await self._connect()

        # We always create the account DB as it is a NO-OP if it already exists
        await self._create_account_db()

        return self

    async def close(self) -> None:
        await self.pool.close()

    def get_table_name(self, table_name: str, service_id: int) -> str:
        return f'{table_name}_{service_id}'

    async def _connect(self) -> AsyncConnectionPool:
        '''
        Connects to the Postgres SQL server
        '''

        pool = AsyncConnectionPool(
            conninfo=f'{self.connection_string}/{DB_NAME}', open=False,
            kwargs={'row_factory': dict_row}
        )
        await pool.open()

        return pool

    async def get_table_columns(self, table_name, _: UUID) -> list:
        '''
        Get the columns and types of
        '''

        stmt: str = (f'''
            SELECT attname, format_type(atttypid, atttypmod) AS type
            FROM   pg_attribute
            WHERE  attrelid = '{table_name}'::regclass
                AND    attnum > 0
                AND    NOT attisdropped
            ORDER  BY attnum;
        ''')

        rows: list[dict] | None = await self.execute(stmt, fetchall=True)

        sql_columns: dict[str, any] = {
            row['attname']: row['type'] for row in rows
        }

        return sql_columns

    def supports_strict(self) -> str:
        '''
        Does this sql-derived class support the 'STRICT' keyword for
        handling data types

        :returns: ''
        '''

        return ''

    def get_column_type(self, data_type) -> str:
        '''
        Get the storage type that Postgresql supports
        '''

        if data_type.upper() == 'BLOB':
            return 'bytea'

        if data_type.upper() == 'REAL':
            return 'float8'

        return data_type

    def get_native_datatype(self, val: str | DataType) -> str:
        if isinstance(val, DataType):
            val = val.value

        return {
            'string': 'TEXT',
            'integer': 'INTEGER',
            'number': 'REAL',
            'boolean': 'INTEGER',
            'uuid': 'TEXT',
            'date-time': 'FLOAT8',
            'array': 'bytea',
            'object': 'bytea',
            'reference': 'TEXT',
        }[val.lower()]

    @staticmethod
    def _create_database(connection_string: str) -> None:
        stmt: str = f'CREATE DATABASE byoda;'

        conn: Connection[Tuple] = connect(connection_string, autocommit=True)

        try:
            conn.execute(stmt)
        except (DuplicateObject, DuplicateDatabase):
            pass
        except Exception as exc:
            _LOGGER.debug(f'Could not create database: {exc}')

        conn.close()

    @staticmethod
    def get_named_placeholder(variable: str) -> str:
        return f'%({variable})s'

    def get_row_count(self, result: int) -> int:
        return result

    def has_rowid(self) -> bool:
        '''
        Postgresql does not have an implicit rowid column that auto-increments
        and is unique
        '''

        return False

    @staticmethod
    def _destroy_database(connection_string) -> None:
        if not config.test_case:
            raise ValueError(
                'We do not delete databases unless we are running a test case'
            )

        conn: Connection[Tuple] = connect(connection_string, autocommit=True)

        try:
            conn.execute('DROP DATABASE byoda')
        except InvalidCatalogName:
            pass
        except ObjectInUse as exc:
            _LOGGER.debug(
                f'Can not delete DB byoda: {exc}'
                'Dropping all tables instead.'
            )
            conn.close()
            conn = connect(f'{connection_string}/byoda', autocommit=True)
            results: Cursor[tuple] = conn.execute(
                'SELECT table_name FROM information_schema.tables '
                "WHERE table_schema='public'"
            )
            for row in results:
                table = row[0]
                _LOGGER.debug(f'Dropping table {table}')
                conn.execute(f'DROP TABLE {table}')

        conn.close()

    async def execute(self, command: str, member_id: UUID | None = None,
                      data: dict[str, AnyScalarType] = None,
                      autocommit: bool = True,
                      fetchall: bool | None = None
                      ) -> int | dict | list[dict] | None:
        _LOGGER.debug(
            f'Executing SQL for member {member_id}: {command} using '
            f'values {data}'
        )

        try:
            async with self.pool.connection() as conn:
                result: AsyncCursor[dict] = await conn.execute(command, data)
        except (CheckViolation, UniqueViolation) as exc:
            raise ValueError(exc)
        except Exception as exc:
            _LOGGER.debug(f'SQL command failed: {exc}')
            raise

        if fetchall is None:
            return result.rowcount
        if fetchall is False:
            return await result.fetchone()

        return await result.fetchall()

    async def backup_datastore(self, server: PodServer) -> None:
        '''
        Backs up the account DB and the membership DB files
        to the cloud. If a DB file has not changed since
        the last backup, it will not be uploaded to the cloud

        :raises: ValueError if the server is running locally
        '''

        if server.cloud == CloudType.LOCAL:
            raise ValueError('Cannot backup to local storage')

        data_secret: DataSecret = server.account.data_secret

        cloud_file_store: FileStorage = server.document_store.backend

        protected_cloud_filepath: str = (
            self.paths.get(Paths.ACCOUNT_DATA_DIR) +
            f'{BACKUP_FILE}.{PROTECTED_FILE_EXTENSION}'
        )
        local_filepath: str = \
            self.paths.get(Paths.ACCOUNT_DATA_DIR) + f'/{BACKUP_FILE}'

        protected_local_filepath: str = \
            f'{local_filepath}.{PROTECTED_FILE_EXTENSION}'
        try:
            subprocess.run(
                [
                    'pg_dump',
                    '-U', 'postgres',
                    '-d', 'byoda',
                    '-h', 'postgres',
                    '--compress=gzip:9',
                    '-f', local_filepath
                ]
            )
            _LOGGER.debug(f'Created backup file: {local_filepath}')

            data_secret.encrypt_file(local_filepath, protected_local_filepath)
            _LOGGER.debug(
                f'Encrypted the backup file: {protected_local_filepath}'
            )

            with open(protected_local_filepath, 'rb') as file_desc:
                await cloud_file_store.write(
                    protected_cloud_filepath, file_descriptor=file_desc
                )
                _LOGGER.debug(
                    f'Saved backup to cloud: {protected_cloud_filepath}'
                )
            os.remove(local_filepath)
        except Exception as exc:
            _LOGGER.critical(f'Could not backup database: {exc}')

    @staticmethod
    async def restore_backup(connection_string: str, server: PodServer) -> None:
        '''
        Restores the account DB and membership DB files from the cloud
        '''

        log_data: dict[str, any] = {
            'connection_string': connection_string,
        }

        account: Account = server.account
        self = PostgresStorage(
            connection_string, account.paths, account.data_secret
        )

        if server.cloud == CloudType.LOCAL:
            raise ValueError('Cannot restore from local storage')

        cloud_file_store: FileStorage = server.document_store.backend

        protected_cloud_filepath: str = (
            self.paths.get(Paths.ACCOUNT_DATA_DIR) +
            f'{BACKUP_FILE}.{PROTECTED_FILE_EXTENSION}'
        )
        log_data['protected_cloud_filepath'] = protected_cloud_filepath
        _LOGGER.info(f'Restoring DB from cloud', extra=log_data)
        local_filepath: str = \
            self.paths.get(Paths.ACCOUNT_DATA_DIR) + '/{BACKUP_FILE}'
        log_data['local_filepath'] = local_filepath
        protected_local_filepath: str = \
            f'{local_filepath}.{PROTECTED_FILE_EXTENSION}'
        try:
            with open(protected_local_filepath, 'wb') as file_desc:
                await cloud_file_store.read(
                    protected_cloud_filepath, file_descriptor=file_desc
                )
                _LOGGER.debug('Retrieved backup from cloud', extra=log_data)

            data_secret: DataSecret = server.account.data_secret

            data_secret.decrypt_file(protected_local_filepath, local_filepath)
            _LOGGER.debug('Decrypted the backup file', extra=log_data)

            subprocess.run(
                [
                    'pg_restore',
                    '-U', 'postgres',
                    '-d', 'byoda',
                    '-h', 'postgres',
                    '--clean',
                    '--if-exists',
                    local_filepath
                ]
            )
            _LOGGER.debug('Restored backup file', extra=log_data)
        except Exception as exc:
            log_data['exception'] = exc
            _LOGGER.critical('Could not restore database', extra=log_data)
