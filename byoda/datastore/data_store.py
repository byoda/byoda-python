'''
The data store handles storing the data of a pod for a service that
the pod is a member of.

The DataStore can be extended to support different backend storage. It
currently only supports Sqlite3.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


from enum import Enum
from uuid import UUID
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger

from opentelemetry.trace import get_tracer
from opentelemetry.sdk.trace import Tracer

from byoda.datamodel.table import Table

from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.dataclass import SchemaDataObject
from byoda.datamodel.table import QueryResult

from byoda.datatypes import IdType
from byoda.datatypes import MemberStatus
from byoda.datatypes import MemberInfo

from byoda.storage.sqlite import SqliteStorage

from byoda.secrets.data_secret import DataSecret

_LOGGER: Logger = getLogger(__name__)
TRACER: Tracer = get_tracer(__name__)

Schema = TypeVar('Schema')
PodServer = TypeVar('PodServer')


class DataStoreType(Enum):
    SQLITE              = 'sqlite'          # noqa=E221


class DataStore:
    def __init__(self):
        self.backend: SqliteStorage | None = None
        self.store_type: DataStoreType | None = None

    @staticmethod
    async def get_data_store(server: PodServer,
                             storage_type: DataStoreType,
                             data_secret: DataSecret):
        '''
        Factory for initiating a document store
        '''

        _LOGGER.debug(f'Setting up data store of type {storage_type}')

        data_store = DataStore()
        if storage_type == DataStoreType.SQLITE:
            data_store.backend = await SqliteStorage.setup(
                server, data_secret
            )
        else:
            raise ValueError(f'Unsupported storage type: {storage_type}')

        return data_store

    def get_table(self, member_id: UUID, class_name: str) -> Table:
        '''
        Returns the Table instance for the given class name
        '''

        return self.backend.get_table(member_id, class_name)

    async def setup_member_db(self, member_id: UUID, service_id: int,
                              schema: Schema) -> None:
        '''
        Sets up the member database, creating it if it does not exist
        '''

        if not schema.data_classes:
            raise ValueError('No data classes available')

        await self.backend.setup_member_db(member_id, service_id)

        for data_class in schema.data_classes.values():
            if data_class.defined_class:
                _LOGGER.debug(
                    'Skipping setting up a table for defined class '
                    f'{data_class.name}'
                )
                continue

            if data_class.cache_only:
                _LOGGER.debug(
                    'Skipping setting up a table for cache-only class '
                    f'{data_class.name}'
                )
                continue

            created_tables: int = await self.create_table(
                member_id, data_class
            )
            _LOGGER.debug(
                f'Created {created_tables} tables for {data_class.name}'
            )

    async def create_table(self, member_id: UUID,
                           data_class: SchemaDataArray | SchemaDataObject,
                           ) -> int:
        '''
        Creates the table for the given data class. If the data_class
        references another (object) data_class, then we look at the
        fields of that object data_class to see if any of them are
        arrays of objects. If so, we create a table for that array as well.

        :param member_id:
        :param data_class:
        :param data_classes:
        :returns: number of tables created
        '''

        if self.backend.get_sql_table(member_id, data_class.name):
            _LOGGER.debug(
                f'Skipping creation of a table for {data_class.name} '
                'as it already exists'
            )
            return 0

        _LOGGER.debug(f'Creating a table for {data_class.name}')

        if data_class.is_scalar:
            raise ValueError('We do not create tables for scalar data classes')

        sql_table = await self.backend.create_table(member_id, data_class)
        self.backend.add_sql_table(member_id, data_class.name, sql_table)

        return 1

    @TRACER.start_as_current_span('Data_Store.get_memberships')
    async def get_memberships(self, status: MemberStatus = MemberStatus.ACTIVE
                              ) -> dict[UUID, MemberInfo]:
        '''
        Get the latest status of all memberships

        :param status: The status of the membership to return. If its value is
        'None' the latest membership status for all memberships will be. If the
        status parameter has a value, only the memberships with that status are
        returned
        '''

        data = await self.backend.get_memberships(status)

        results: dict[UUID, object] = {
            member_id: membership._asdict()
            for member_id, membership in data.items()
        }
        return results

    @TRACER.start_as_current_span('Data_Store.query')
    async def query(self, member_id: UUID,
                    data_class: SchemaDataArray | SchemaDataObject,
                    filters: dict[str, dict], first: int | None = None,
                    after: str | None = None, fields: set[str] | None = None
                    ) -> list[QueryResult] | None:
        '''
        Queries the datastore backend for data matching the specified criteria.
        This method performs sub-queries for referenced data classes.

        :param member_id: member_id for the member DB to execute the command on
        :param data_class: the data class for which to get data
        :param filters: the filters to be applied to the query
        :param first: the number of records to return
        :param cursor: pagination cursor calculated for the data
        :returns: list of tuples with for each item the data matching the
        specified criteria and the metadata for that data or None if no data
        was found
        :raises:
        '''

        data: list[QueryResult] = await self.backend.query(
            member_id, data_class.name, filters, first=first, after=after,
            fields=fields
        )

        return data

    @TRACER.start_as_current_span('Data_Store.mutate')
    async def mutate(self, member_id: UUID, class_name: str,
                     data: dict[str, object], cursor: str,
                     origin_id: UUID | None, origin_id_type: IdType | None,
                     data_filter_set: DataFilterSet = None) -> int:
        '''
        mutate the data in the cache store for the data class

        :param member_id: member_id for the member DB to execute the command on
        :param class_name: the name of the data_class that we need to append to
        :param data: k/v pairs for data to be stored in the table
        :param cursor: pagination cursor calculated for the data
        :param origin_id: the ID of the source for the data
        :param origin_id_type: the type of ID of the source for the data
        :returns: the number of rows added to the table
        '''

        return await self.backend.mutate(
            member_id, class_name, data, cursor=cursor,
            origin_id=origin_id, origin_id_type=origin_id_type,
            origin_class_name=None, data_filter_set=data_filter_set
        )

    @TRACER.start_as_current_span('CacheStore.append')
    async def append(self, member_id: UUID, data_class: SchemaDataArray,
                     data: dict[str, object], cursor: str,
                     origin_id: UUID, origin_id_type: IdType) -> int:
        '''
        append the data to the data store for the data class

        :param member_id: member_id for the member DB to execute the command on
        :param class_name: the name of the data_class that we need to append to
        :param data: k/v pairs for data to be stored in the table
        :param cursor: pagination cursor calculated for the data
        :returns: the number of rows added to the table
        '''

        result = await self.backend.append(
            member_id, data_class.name, data, cursor, origin_id,
            origin_id_type, origin_class_name=None
        )

        return result

    @TRACER.start_as_current_span('Data_Store.delete')
    async def delete(self, member_id: UUID, class_name: str,
                     data_filter_set: DataFilterSet = None) -> int:
        return await self.backend.delete(
            member_id, class_name, data_filter_set
        )

    async def close(self):
        await self.backend.close()
