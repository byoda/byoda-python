'''
The data store handles storing the data of a pod for a service that
the pod is a member of.

The CacheStore can be extended to support different backend storage. It
currently only supports Sqlite3.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from enum import Enum
from uuid import UUID
from logging import getLogger
from typing import TypeVar
from datetime import datetime
from datetime import timezone

from anyio import create_task_group
from anyio import sleep

from opentelemetry.trace import get_tracer
from opentelemetry.sdk.trace import Tracer

from byoda.datamodel.network import Network
from byoda.datamodel.memberdata import MemberData
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.dataclass import SchemaDataObject
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.table import Table
from byoda.datamodel.table import QueryResult

from byoda.datamodel.table import META_ID_COLUMN
from byoda.datamodel.table import META_ID_TYPE_COLUMN
from byoda.datamodel.table import CACHE_ORIGIN_CLASS_COLUMN

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType
from byoda.datatypes import DataFilterType

from byoda.secrets.secret import Secret

from byoda.storage.sqlite import SqliteStorage

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda.exceptions import ByodaRuntimeError

Schema = TypeVar('Schema')
PodServer = TypeVar('PodServer')
Member = TypeVar('Member')

_WorkQueue = dict[UUID, dict[IdType, dict[str, list[QueryResult]]]]

_LOGGER: Logger = getLogger(__name__)
TRACER: Tracer = get_tracer(__name__)

EXPIRE_THRESHOLD: int = 900
REFRESH_THRESHOLD: int = 14400


class CacheStoreType(Enum):
    SQLITE              = 'sqlite'          # noqa=E221


class CacheStore:
    def __init__(self):
        self.backend: SqliteStorage = None
        self.store_type: CacheStoreType = None

    @staticmethod
    async def get_cache_store(server: PodServer, storage_type: CacheStoreType):
        '''
        Factory for initiating a document store
        '''

        _LOGGER.debug(f'Setting up cache store of type {storage_type}')

        cache_store = CacheStore()
        if storage_type == CacheStoreType.SQLITE:
            cache_store.backend = await SqliteStorage.setup(
                server, None
            )
        else:
            raise ValueError(f'Unsupported storage type: {storage_type}')

        return cache_store

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

            if not data_class.cache_only:
                _LOGGER.debug(
                    'Skipping setting up a table for non-caching class '
                    f'{data_class.name}'
                )
                continue

            created_tables: int = await self.create_table(
                member_id, data_class
            )
            _LOGGER.debug(
                f'Created {created_tables} tables for {data_class.name} '
                f'in store {type(self)}'
            )

    async def create_table(self, member_id: UUID,
                           data_class: SchemaDataArray | SchemaDataObject
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

        created: int = 0
        if self.backend.get_sql_table(member_id, data_class.name):
            _LOGGER.debug(
                f'Skipping creating a table for {data_class.name} '
                'as it already exists'
            )
            return created

        _LOGGER.debug(f'Creating a table for caching {data_class.name}')

        if data_class.is_scalar:
            raise ValueError('We do not create tables for scalar data classes')

        sql_table = await self.backend.create_table(member_id, data_class)
        self.backend.add_sql_table(member_id, data_class.name, sql_table)

        return 1

    @TRACER.start_as_current_span('CacheStore.query')
    async def query(self, member_id: UUID,
                    data_class: SchemaDataArray | SchemaDataObject,
                    filters: DataFilterSet, first: int = None,
                    after: str = None, fields: set[str] | None = None,
                    meta_filters: DataFilterSet | None = None
                    ) -> list[QueryResult] | None:
        '''
        Queries the cache store backend for data matching the specified
        criteria. This method performs sub-queries for referenced data classes.

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
            fields=fields, meta_filters=meta_filters
        )

        return data

    @TRACER.start_as_current_span('CacheStore.mutate')
    async def mutate(self, member_id: UUID, class_name: str,
                     data: dict[str, object], cursor: str,
                     origin_id: UUID | None, origin_id_type: IdType | None,
                     origin_class_name: str | None = None,
                     data_filter_set: DataFilterSet = None) -> int:
        '''
        mutate the data in the cache store for the data class

        :param member_id: member_id for the member DB to execute the command on
        :param class_name: the name of the data_class that we need to append to
        :param data: k/v pairs for data to be stored in the table
        :param cursor: pagination cursor calculated for the data
        :param origin_id: the ID of the source for the data
        :param origin_id_type: the type of ID of the source for the data
        :param origin_class_name: the class from which the data was fetched
        :returns: the number of rows added to the table
        '''

        return await self.backend.mutate(
            member_id, class_name, data, cursor=cursor,
            origin_id=origin_id, origin_id_type=origin_id_type,
            origin_class_name=origin_class_name,
            data_filter_set=data_filter_set
        )

    @TRACER.start_as_current_span('CacheStore.append')
    async def append(self, member_id: UUID, data_class: SchemaDataArray,
                     data: dict[str, object], cursor: str,
                     origin_id: UUID, origin_id_type: IdType,
                     origin_class_name: str) -> int:
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
            origin_id_type, origin_class_name
        )

        return result

    @TRACER.start_as_current_span('CacheStore.delete')
    async def delete(self, member_id: UUID, class_name: str,
                     data_filter_set: DataFilterSet = None) -> int:
        return await self.backend.delete(
            member_id, class_name, data_filter_set
        )

    async def close(self):
        await self.backend.close()

    @TRACER.start_as_current_span('CacheStore.refresh_table')
    async def refresh_table(self, server: PodServer, member: Member,
                            data_class: SchemaDataArray,
                            timestamp: int | float | datetime | None = None
                            ) -> int:
        '''
        Refreshes content in the cache

        :param member_id: the member_id for the cache store
        :param class_name: the name of the table to purge
        :param timestamp: the timestamp (in seconds) before which data should
        be deleted. If not specified, the current time plus the expiration time
        specified for the data class is used
        '''

        member_id: UUID = member.member_id

        data: list[QueryResult] = await self._get_refreshable_data(
            member_id, data_class.name, timestamp
        )

        if not data or len(data) == 0:
            return 0

        class_name: str = data_class.name
        work_queue: _WorkQueue = self._get_workqueue(data, class_name)

        origin_id: UUID
        origin_id_type: IdType
        async with create_task_group() as tg:
            for origin_id in work_queue:
                for origin_id_type, work in work_queue[origin_id].items():
                    tg.start_soon(
                        self._refresh_from_source,
                        server, member, data_class, origin_id, origin_id_type,
                        work
                    )

        return len(data)

    async def _refresh_from_source(self, server: PodServer, member: Member,
                                   data_class: SchemaDataArray,
                                   origin_id: UUID, origin_id_type: IdType,
                                   stale_items: dict[str, list[QueryResult]]
                                   ) -> None:
        '''
        Gets refreshed data from the source and stores it in the destination
        table in the cache

        :param member: our membership of the service
        :param data_class: class that should be updated with refreshed data
        :param origin_id: The UUID of the origin for the data
        :param origin_id_type: what type of origin the data was fetched from
        :param stale_items: dict with keys the class_name where the data was
        retrieved from and as values the data that was retrieved originally
        from the source and is now stored in this table in the cache
        returns: (none)
        '''

        network: Network = member.network
        service_id: int = member.service_id
        member_id: UUID = member.member_id
        tls_secret: Secret = member.tls_secret

        query_results: list[QueryResult]
        for origin_class_name, query_results in stale_items.items():
            stale_data: dict[str, object]
            for stale_data, _ in query_results:
                filter_items: DataFilterType = {}

                ref_class: SchemaDataObject = data_class.referenced_class
                required_fields: list[str] = ref_class.required_fields
                for field in required_fields:
                    if isinstance(stale_data[field], datetime):
                        filter_items[field] = {
                            'at': stale_data[field].timestamp()
                        }
                    else:
                        filter_items[field] = {'eq': stale_data[field]}

                try:
                    resp: HttpResponse = await DataApiClient.call(
                        service_id, origin_class_name, DataRequestType.QUERY,
                        secret=tls_secret, network=network.name,
                        member_id=origin_id, depth=0, data_filter=filter_items
                    )

                    if not resp or resp.status_code != 200:
                        _LOGGER.debug(
                            f'Refresh query to {origin_id_type.value}'
                            f'{origin_id} for class {origin_class_name} with '
                            f'filters {filter_items} failed, status: '
                            f'{resp.status_code}'
                        )
                        await sleep(1)
                        continue
                except ByodaRuntimeError as exc:
                    _LOGGER.debug(
                        f'Refresh query to {origin_id_type.value}{origin_id} '
                        f'for class {origin_class_name} with filters '
                        f'{filter_items} failed: {exc}'
                    )
                    await sleep(1)
                    continue

                request_data: dict[str, any] = resp.json()

                if request_data['total_count'] == 0:
                    _LOGGER.debug(
                        f'Stale data is no longer available from '
                        f'{origin_id_type.value}{origin_id}'
                    )

                    data_filter: DataFilterSet = DataFilterSet(
                        filter_items, data_class=data_class
                    )
                    await MemberData.delete_data(
                        server, member, data_class, data_filter
                    )

                    continue
                elif request_data['total_count'] > 1:
                    _LOGGER.info(
                        f'Got multiple results from {origin_id_type.value}'
                        f'{origin_id} with filters: {filter_items}. That is '
                        'odd, deleting stale item'
                    )
                    await MemberData.delete_data(
                        server, member, data_class, data_filter
                    )
                    continue

                edges: list[dict[str, object]] = request_data['edges']
                renewed_data: dict[str, object] = edges[0]['node']
                cursor: str = Table.get_cursor_hash(
                    renewed_data, origin_id, required_fields
                )
                data_filter_set = DataFilterSet(
                    filter_items, data_class=data_class
                )

                result = await self.mutate(
                    member_id, data_class.name, renewed_data, cursor,
                    origin_id=origin_id, origin_id_type=origin_id_type,
                    origin_class_name=origin_class_name,
                    data_filter_set=data_filter_set
                )

                return result

    async def _get_refreshable_data(self, member_id: UUID, class_name: str,
                                    timestamp: int | float | datetime
                                    ) -> list[QueryResult]:
        '''
        Get data needs to be renewed

        :param member_id: the member_id for the cache store
        :param class_name: the name of the table to purge
        :param timestamp: the timestamp (in seconds) before which data should
        be deleted. If not specified, the current time plus the expiration time
        specified for the data class is used
        '''

        seconds: float | int
        if not timestamp:
            # We want to refresh content that will expire at
            # now() + REFRESH_THRESHOLD, as we want to refresh content
            # before it expires
            seconds = \
                datetime.now(tz=timezone.utc).timestamp() + REFRESH_THRESHOLD
        elif isinstance(timestamp, datetime):
            seconds = timestamp.timestamp()
        elif type(timestamp) in (int, float):
            seconds = timestamp
        else:
            raise ValueError(f'Invalid timestamp type: {type(timestamp)}')

        meta_data_filter = DataFilterSet(
            {'expires': {'elt': seconds}}, is_meta_filter=True
        )

        data: list[QueryResult] = await self.backend.query(
            member_id, class_name, meta_filters=meta_data_filter
        ) or []

        return data

    def _get_workqueue(self, data: list[QueryResult], class_name: str
                       ) -> _WorkQueue:
        '''
        Returns work queues data structure to fetch data from its origins

        The work is split per origin_id/origin_id_type so that we can
        avoid flooding a single source with requests and instead can
        sequentially request data from each source.

        :param data: the data to be refreshed
        :param class_name: the name of the class where to store the
        refreshed data
        :returns: a deep dict structure:
            OriginId / OriginIdType / OriginClass -> list[QueryResult]
        '''

        # work_q: OriginId / OriginIdType / OriginClass -> list[QueryResult]
        work_q: _WorkQueue = {}

        item: QueryResult
        for item in data:
            metadata: dict[str, str | int | float] = item.metadata
            data: dict[str, object] = item.data

            origin_id: UUID = UUID(metadata[META_ID_COLUMN])
            if origin_id not in work_q:
                work_q[origin_id] = {}

            origin_id_type = IdType(metadata[META_ID_TYPE_COLUMN])
            if origin_id_type != IdType.MEMBER:
                # TODO
                raise NotImplementedError(
                    f'Refreshing data from entity {origin_id_type.value} '
                    f'is not yet implemented'
                )
            if origin_id_type not in work_q[origin_id]:
                work_q[origin_id][origin_id_type] = {}

            origin_class_name: str = metadata[CACHE_ORIGIN_CLASS_COLUMN]
            if origin_class_name not in work_q[origin_id][origin_id_type]:
                work_q[origin_id][origin_id_type][origin_class_name] = []
                _LOGGER.debug(
                    f'Created work queue: {origin_id_type.value}'
                    f'{origin_id} for origin class {origin_class_name} '
                    f'to store in class {class_name}'
                )

            work_q[origin_id][origin_id_type][origin_class_name].append(item)

        return work_q

    @TRACER.start_as_current_span('CacheStore.expire_table')
    async def expire_table(self, server: PodServer, member: UUID,
                           data_class: SchemaDataArray,
                           timestamp: int | float | datetime | None = None
                           ) -> int:
        '''
        Purges expired content from the cache

        :param member_id: the member_id for the cache store
        :param class_name: the name of the table to purge
        :param timestamp: the timestamp (in seconds) before which data should
        be deleted. If not specified, the current time plus the expiration time
        specified for the data class is used
        '''

        seconds: float | int
        if not timestamp:
            # We add 900 seconds to the current time so we'll delete data that
            # expires in the next 15 minutes
            seconds: float = \
                datetime.now(tz=timezone.utc).timestamp() + EXPIRE_THRESHOLD
        elif isinstance(timestamp, datetime):
            seconds = timestamp.timestamp()
        elif type(timestamp) in (int, float):
            seconds = timestamp
        else:
            raise ValueError(f'Invalid timestamp type: {type(timestamp)}')

        data_filter = DataFilterSet(
            {'expires': {'lt': seconds}}, data_class=data_class,
            is_meta_filter=True
        )
        items_deleted: int = await MemberData.delete_data(
            server, member, data_class, data_filter
        )

        return items_deleted
