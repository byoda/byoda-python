'''
The data store handles storing the data of a pod for a service that
the pod is a member of.

The DataStore can be extended to support different backend storage. It
currently only supports SqLite3.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from enum import Enum
from uuid import UUID
from typing import TypeVar

from byoda.datamodel.datafilter import DataFilterSet

from byoda.storage.sqlite import SqliteStorage

_LOGGER = logging.getLogger(__name__)

Schema = TypeVar('Schema')


class DataStoreType(Enum):
    SQLITE              = 'sqlite'          # noqa=E221


class DataStore:
    def __init__(self):
        self.backend: SqliteStorage = None
        self.store_type: DataStoreType = None

    @staticmethod
    async def get_data_store(storage_type: DataStoreType):
        '''
        Factory for initiating a document store
        '''

        storage = DataStore()
        if storage_type == DataStoreType.SQLITE:
            storage.backend = await SqliteStorage.setup()
        else:
            raise ValueError(f'Unsupported storage type: {storage_type}')

        return storage

    async def setup_member_db(self, member_id: UUID, service_id: int,
                              schema: Schema) -> None:
        '''
        '''
        await self.backend.setup_member_db(member_id, service_id, schema)

    async def query(self, member_id: UUID, key: str, filters: dict[str, dict]
                    ) -> dict[str, object]:

        return await self.backend.query(member_id, key, filters)

    async def mutate(self, member_id: UUID, key: str, data: dict[str, object],
                     data_filter_set: DataFilterSet = None) -> int:
        return await self.backend.mutate(member_id, key, data, data_filter_set)

    async def append(self, member_id: UUID, key: str, data: dict[str, object]):
        return await self.backend.append(member_id, key, data)

    async def delete(self, member_id: UUID, key: str,
                     data_filter_set: DataFilterSet = None) -> int:
        return await self.backend.delete(member_id, key, data_filter_set)

    async def close(self):
        await self.backend.close()