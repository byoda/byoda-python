'''
The data store handles storing the data of a pod for a service that
the pod is a member of.

The DataStore can be extended to support different backend storage. It
currently only supports SqLite3.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
from enum import Enum
from uuid import UUID
from typing import TypeVar

from byoda.datatypes import MemberStatus

from byoda.datamodel.datafilter import DataFilterSet

from byoda.storage.sqlite import SqliteStorage

from byoda.secrets.data_secret import DataSecret
from byoda import config

_LOGGER = logging.getLogger(__name__)

Schema = TypeVar('Schema')


class DataStoreType(Enum):
    SQLITE              = 'sqlite'          # noqa=E221


class DataStore:
    def __init__(self):
        self.backend: SqliteStorage = None
        self.store_type: DataStoreType = None

    @staticmethod
    async def get_data_store(storage_type: DataStoreType,
                             data_secret: DataSecret):
        '''
        Factory for initiating a document store
        '''

        _LOGGER.debug(f'Setting up data store of type {storage_type}')
        
        storage = DataStore()
        if storage_type == DataStoreType.SQLITE:
            storage.backend = await SqliteStorage.setup(
                config.server, data_secret
            )
        else:
            raise ValueError(f'Unsupported storage type: {storage_type}')

        return storage

    async def setup_member_db(self, member_id: UUID, service_id: int,
                              schema: Schema) -> None:
        '''
        Sets up the member database, creating it if it does not exist
        '''
        await self.backend.setup_member_db(member_id, service_id, schema)

    async def get_memberships(self, status: MemberStatus = MemberStatus.ACTIVE
                              ) -> dict[str, object]:
        '''
        Get the latest status of all memberships

        :param status: The status of the membership to return. If its value is
        'None' the latest membership status for all memberships will be. If the
        status parameter has a value, only the memberships with that status are
        returned
        '''

        return await self.backend.get_memberships(status)

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
