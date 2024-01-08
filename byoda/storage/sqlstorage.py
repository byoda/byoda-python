'''
The generic SQL class takes care of converting the data schema of
a service to a SQL table. Classes for different SQL flavors and
implementations should derive from this class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger

import aiosqlite

from byoda.datamodel.sqltable import SqlTable
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.table import Table
from byoda.datamodel.table import QueryResult

from byoda.datatypes import IdType
from byoda.datatypes import AnyScalarType

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

    async def execute(self, command: str, member_id: UUID = None,
                      data: dict[str, AnyScalarType] = None,
                      autocommit: bool = True, fetchall: bool = False
                      ) -> aiosqlite.cursor.Cursor | list[aiosqlite.Row]:
        '''
        Executes the SQL command.

        :param command: SQL command to execute
        :parm member_id: member_id for the member DB to execute the command on
        :param data: data to use for the named placeholders in the SQL command
        :param autocommit: whether to commit the transaction after executing
        :param fetchall: should rows be fetched and returned
        :returns: if 'fetchall' is False, the Cursor to the result, otherwise
        a list of rows returned by the query
        '''

        datafile: str = self.database_filepath(member_id)

        if member_id:
            _LOGGER.debug(
                f'Executing SQL for member {member_id}: {command} using '
                f'SQL data file {self.member_db_files[member_id]} and '
                f'values {data}'
            )
        else:
            _LOGGER.debug(
                f'Executing SQL for account: {command} using '
                f'SQL data file {self.account_db_file} and values {data}'
            )

        async with aiosqlite.connect(datafile) as db_conn:
            db_conn.row_factory = aiosqlite.Row
            await db_conn.execute('PRAGMA synchronous = normal')

            try:
                if not fetchall:
                    result: aiosqlite.cursor.Cursor = \
                        await db_conn.execute(command, data)
                else:
                    result: list[aiosqlite.Row] = \
                        await db_conn.execute_fetchall(command, data)

                if autocommit:
                    _LOGGER.debug(
                        f'Committing transaction for SQL command: {command}'
                    )
                    await db_conn.commit()

                return result
            except aiosqlite.Error as exc:
                await db_conn.rollback()
                _LOGGER.error(
                    f'Error executing SQL: {exc}'
                )

                raise RuntimeError(exc)

    def get_table(self, member_id: UUID, class_name: str) -> Table:
        '''
        Returns the table for the class of the member_id
        '''

        if class_name not in self.member_sql_tables[member_id]:
            _LOGGER.error(
                f'Table {class_name} not found for member {member_id}. '
                f'Known tables: {", ".join(self.member_sql_tables[member_id])}'
            )

        sql_table: SqlTable = self.member_sql_tables[member_id][class_name]
        return sql_table

    def get_tables(self, member_id) -> list[Table]:
        '''
        Returns the tables for the member_id
        '''

        return list(self.member_sql_tables[member_id].values())

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
        return await sql_table.delete(data_filter_set)

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
