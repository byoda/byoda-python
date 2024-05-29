'''
The generic SQL class takes care of converting the data schema of
a service to a SQL table. Classes for different SQL flavors and
implementations should derive from this class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from uuid import UUID
from typing import TypeVar
from datetime import UTC
from datetime import datetime
from logging import getLogger
from byoda.util.logger import Logger

from byoda.datamodel.sqltable import SqlTable
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.table import Table
from byoda.datamodel.table import QueryResult
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.dataclass import SchemaDataObject

from byoda.datatypes import MemberInfo
from byoda.datatypes import MemberStatus

from byoda.datatypes import IdType

Member = TypeVar('Member')
Schema = TypeVar('Schema')
PodServer = TypeVar('PodServer')
DocumentStore = TypeVar('DocumentStore')
DataStore = TypeVar('DataStore')
FileStorage = TypeVar('FileStorage')

_LOGGER: Logger = getLogger(__name__)


class Sql:
    def __init__(self) -> None:
        self.account_db_file: str = None
        self.member_db_files: dict[str, str] = {}
        self.connection_string: str | None = None

        self.account_sql_table: SqlTable | None = None
        self.member_sql_tables: dict[UUID, dict[str, SqlTable]] = {}

    def database_filepath(self, member_id: UUID = None) -> str:
        if not member_id:
            filepath: str = self.account_db_file

            _LOGGER.debug(f'Using account DB file: {filepath}')
        else:
            filepath: str = self.member_db_files.get(
                member_id
            )
            _LOGGER.debug(
                f'Using member DB file for member_id {member_id}: {filepath}'
            )
            if not filepath:
                raise ValueError(f'No DB for member_id {member_id}')

        return filepath

    def get_table(self, member_id: UUID, class_name: str) -> Table:
        '''
        Returns the SQL table for the class of the member_id
        '''

        if member_id not in self.member_sql_tables:
            _LOGGER.error(f'No tables found for member {member_id}')
            raise ValueError(f'No tables found for member {member_id}')

        if class_name not in self.member_sql_tables[member_id]:
            _LOGGER.error(
                f'Table {class_name} not found for member {member_id}. '
                f'Known tables: {", ".join(self.member_sql_tables[member_id])}'
            )
            raise ValueError(f'No table available for {class_name}')

        sql_table: SqlTable = self.member_sql_tables[member_id][class_name]
        return sql_table

    def get_sql_table(self, member_id: UUID, class_name: str
                      ) -> SqlTable | None:
        '''
        Returns the SQL table for the membership if it exists
        '''

        if 'member_id' not in self.member_sql_tables:
            return None

        sql_table: SqlTable = self.member_sql_tables[member_id].get(class_name)

        return sql_table

    def get_tables(self, member_id) -> list[Table]:
        '''
        Returns the tables for the member_id
        '''

        return list(self.member_sql_tables[member_id].values())

    def add_sql_table(self, member_id: UUID, class_name: str,
                      sql_table: SqlTable) -> None:
        '''
        Adds the SQL table to the list of tables we have created for the
        membership
        '''

        _LOGGER.debug(f'Adding table {class_name} for member {member_id}')
        if member_id not in self.member_sql_tables:
            self.member_sql_tables[member_id] = {}

        _LOGGER.debug(f'Adding table {class_name} for member {member_id}')
        self.member_sql_tables[member_id][class_name] = sql_table

    async def create_table(self, member_id,
                           data_class: SchemaDataArray | SchemaDataObject,
                           ) -> SqlTable:
        '''
        Creates a table for a data class in the schema of a membership in
        the Sqlite3 database for the membership

        :param member_id:
        :param data_class: data class to create the table for
        :param data_classes: list of data classes in the schema of the service
        :returns: the created table
        '''

        sql_table: SqlTable = await SqlTable.setup(data_class, self, member_id)

        return sql_table

    async def _create_account_db(self) -> None:
        '''
        Creates the Account DB file
        '''

        await self.execute('''
            CREATE TABLE IF NOT EXISTS memberships(
                member_id TEXT,
                service_id BIGINT,
                timestamp REAL,
                status TEXT
            )
        ''')    # noqa: E501

        _LOGGER.debug(f'Created Account DB {self.account_db_file}')

    async def setup_member_db(self, member_id: UUID, service_id: int) -> None:
        await self.set_membership_status(
            member_id, service_id, MemberStatus.ACTIVE
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
        if status and status.value:
            query += f"WHERE status = '{status.value}'"

        rows: list[dict] = await self.execute(query, fetchall=True)

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

    async def set_membership_status(self, member_id: UUID, service_id: int,
                                    status: MemberStatus) -> None:
        '''
        Sets the status of a membership
        '''

        if not isinstance(member_id, UUID):
            try:
                member_id = UUID(member_id)
            except ValueError as exc:
                _LOGGER.warning(f'Invalid member_id {member_id}: {exc}')
                raise

        # Can't use data dict parameter with 'member_id' key as the
        # SqlTable.execute() method will try to update the SQL tables for
        # the membership if a member_id parameter is specified.
        stmt: str = (f'''
                SELECT member_id, service_id, status, timestamp
                FROM memberships
                WHERE member_id = '{member_id}'
                ORDER BY timestamp DESC
                LIMIT 1
        ''')

        rows: list = await self.execute(stmt, fetchall=True)

        if len(rows) and rows[0]['status'] == status.value:
            _LOGGER.debug('No need to change membership status')
            return

        if len(rows) == 0:
            _LOGGER.debug(f'No membership info found for service {service_id}')
        else:
            db_status: str = rows[0]['status']
            _LOGGER.debug(
                f'Existing status of membership for service {service_id}: '
                f'{db_status}'
            )

        stmt = (f'''
            INSERT INTO memberships (member_id, service_id, status, timestamp)
            VALUES (
                '{member_id}',
                {self.get_named_placeholder('service_id')},
                {self.get_named_placeholder('status')},
                {self.get_named_placeholder('timestamp')}
            )
        ''')

        await self.execute(
           stmt,
           data={
                'service_id': service_id,
                'status': status.value,
                'timestamp': int(datetime.now(tz=UTC).timestamp())
            }
        )

    async def query(self, member_id: UUID, class_name: str,
                    filters: DataFilterSet = None,
                    first: int = None, after: str = None,
                    fields: set[str] | None = None,
                    meta_filters: DataFilterSet | None = None
                    ) -> list[QueryResult] | None:
        '''
        Execute the query on the SqlTable for the member_id and class_name

        :param member_id: member_id for the member DB to execute the command on
        :param class_name: the name of the data_class that we query from
        :param filters: filters to apply to the query
        :param first: number of records to return
        :param after: pagination cursor
        :param fields: fields to include in the response
        :param meta_filters: filters to apply to the metadata
        'parent' data class
        '''

        sql_table: SqlTable = self.get_table(member_id, class_name)

        return await sql_table.query(
            filters, first=first, after=after, fields=fields,
            meta_filters=meta_filters
        )

    async def mutate(self, member_id: UUID, class_name: str,
                     data: dict[str, object], cursor: str,
                     origin_id: UUID, origin_id_type: IdType,
                     origin_class_name: str | None,
                     data_filter_set: DataFilterSet = None
                     ) -> int:
        '''
        Execute the mutation on the SqlTable for the member_id and key

        :param member_id: member_id for the member DB to execute the command on
        :param class_name: the name of the data_class that we need to append to
        :param data: k/v pairs for data to be stored in the table
        :param cursor: pagination cursor calculated for the data
        :param origin_id: the ID of the source for the data
        :param origin_id_type: the type of ID of the source for the data
        :returns: the number of mutated rows in the table
        '''

        if member_id not in self.member_sql_tables:
            raise ValueError(f'No tables found for member {member_id}')

        if class_name not in self.member_sql_tables[member_id]:
            raise ValueError(f'No table available for {class_name}')

        sql_table: SqlTable = self.member_sql_tables[member_id][class_name]
        return await sql_table.mutate(
            data, cursor, origin_id=origin_id, origin_id_type=origin_id_type,
            origin_class_name=origin_class_name,
            data_filters=data_filter_set
        )

    async def append(self, member_id: UUID, class_name: str,
                     data: dict[str, object], cursor: str,
                     origin_id: UUID, origin_id_type: IdType,
                     origin_class_name: str | None) -> int:
        '''
        Execute the append on the SqlTable for the member_id and key

        :param member_id: member_id for the member DB to execute the command on
        :param class_name: the name of the data_class that we need to append to
        :param data: k/v pairs for data to be stored in the table
        :param cursor: pagination cursor calculated for the data
        :returns: the number of rows added to the table
        '''

        if member_id not in self.member_sql_tables:
            raise ValueError(f'No tables found for member {member_id}')

        if class_name not in self.member_sql_tables[member_id]:
            raise ValueError(f'No table available for {class_name}')

        sql_table: SqlTable = self.member_sql_tables[member_id][class_name]

        if cursor is None:
            cursor = Table.get_cursor_hash(
                data, member_id, sql_table.required_fields
            )

        return await sql_table.append(
            data, cursor, origin_id, origin_id_type, origin_class_name
        )

    async def delete(self, member_id: UUID, class_name: str,
                     data_filter_set: DataFilterSet = None) -> int:
        '''
        Execute the delete on the SqlTable for the member_id and class
        '''

        sql_table: SqlTable = self.member_sql_tables[member_id][class_name]
        return await sql_table.delete(
            data_filter_set, sql_table.sql_store.get_named_placeholder
        )

    async def read(self, member: Member, class_name: str,
                   filters: DataFilterSet) -> list[QueryResult]:
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

    async def maintain(self, server: PodServer):
        '''
        Performs perdiodic maintenance tasks
        '''

        raise NotImplementedError(
            'No maintenance method implemented for SQL storage'
        )
