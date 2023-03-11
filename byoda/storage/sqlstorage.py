'''
The generic SQL class takes care of converting the data schema of
a service to a SQL table. Classes for different SQL flavors and
implementations should derive from this class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
from uuid import UUID
from typing import TypeVar

import aiosqlite

from byoda.datamodel.sqltable import SqlTable
from byoda.datamodel.datafilter import DataFilterSet


Member = TypeVar('Member')
Schema = TypeVar('Schema')
PodServer = TypeVar('PodServer')
DocumentStore = TypeVar('DocumentStore')
DataStore = TypeVar('DataStore')
FileStorage = TypeVar('FileStorage')

_LOGGER = logging.getLogger(__name__)


class Sql:
    def __init__(self):
        self.account_db_file: str = None
        self.member_db_files: dict[str, str] = {}

    def database_filepath(self, member_id: UUID = None) -> str:
        if not member_id:
            filepath: str = self.account_db_file

            _LOGGER.debug('Using account DB file')
        else:
            filepath: str = self.member_db_files.get(
                member_id
            )
            _LOGGER.debug(
                f'Using member DB file for member_id {member_id}'
            )
            if not filepath:
                raise ValueError(f'No DB for member_id {member_id}')

        return filepath

    async def execute(self, command: str, member_id: UUID = None,
                      data: dict[str, str | int | float | bool] = None,
                      autocommit: bool = True, fetchall: bool = False
                      ) -> aiosqlite.cursor.Cursor:
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

        datafile = self.database_filepath(member_id)

        if member_id:
            _LOGGER.debug(
                f'Executing SQL for member {member_id}: {command} using '
                f'SQL data file {self.member_db_files[member_id]}'
            )
        else:
            _LOGGER.debug(
                f'Executing SQL for account: {command} using '
                f'SQL data file {self.account_db_file}'
            )

        async with aiosqlite.connect(datafile) as db_conn:
            db_conn.row_factory = aiosqlite.Row
            await db_conn.execute('PRAGMA synchronous = normal')

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
                    _LOGGER.debug(
                        f'Not SQL committing for SQL command {command}'
                    )

                return result
            except aiosqlite.Error as exc:
                await db_conn.rollback()
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

    async def maintain(self, server: PodServer):
        '''
        Performs perdiodic maintenance tasks
        '''

        raise NotImplementedError(
            'No maintenance method implemented for SQL storage'
        )
