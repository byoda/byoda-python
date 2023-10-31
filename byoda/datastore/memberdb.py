'''
Class MemberDb stores information for the Service and Directory servers
about registered clients

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger
from datetime import datetime
from datetime import timezone
from ipaddress import ip_address
from ipaddress import IPv4Address

from byoda.datamodel.schema import Schema
from byoda.datatypes import MemberStatus

from byoda.datacache.kv_cache import KVCache

_LOGGER: Logger = getLogger(__name__)

Member = TypeVar('Member')

MEMBERS_LIST = 'members'
MEMBER_ID_META_FORMAT = '{member_id}-meta'
MEMBER_ID_DATA_FORMAT = '{member_id}-data'


class MemberDb:
    '''
    Store for registered members

    The metadata of a member is stored in the MEMBER_ID_META_FORMAT
    ('{member_id}-meta) while the actual data is stored using the member_id
    string as key
    '''

    def __init__(self, schema: Schema = None):
        '''
        Do not call this constructor directly. Use MemberDb.setup() instead

        :param schema: the schema to use for validation of the data
        :returns: self
        :raises: (none)
        '''

        self.schema: Schema | None = schema
        self._service_id = None

    async def setup(connection_string: str, schema: Schema = None):
        '''
        Factory for the MemberDB class

        :param connection_string:
        :param schema: the schema to use for validation of the data
        '''

        self = MemberDb(schema)
        self.kvcache = await KVCache.create(connection_string)
        return self

    @property
    def service_id(self):
        return self.kvcache.identifier

    @service_id.setter
    def service_id(self, service_id: int):
        self.kvcache.identifier = f'service-{str(service_id)}'

    async def exists(self, member_id: UUID) -> bool:
        '''
        Checks if a member is already in the member-meta hash. This function
        does not check whether the member_id is in the list
        '''

        mid = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))

        exists = await self.kvcache.exists(mid)

        return exists

    async def pos(self, member_id: UUID):
        '''
        Finds the first occurrence of value in the list for the key
        '''

        return await self.kvcache.pos(MEMBERS_LIST, str(member_id))

    async def get_next(self, timeout: int = 0) -> UUID:
        '''
        Remove the first item in the MEMBER_LIST and return it
        '''

        value = await self.kvcache.get_next(MEMBERS_LIST, timeout=timeout)

        if isinstance(value, bytes):
            value = UUID(value.decode('utf-8'))

        return value

    async def add_meta(self, member_id: UUID, remote_addr: IPv4Address,
                       schema_version: int, data_secret: str,
                       status: MemberStatus) -> None:
        '''
        Adds (or overwrites) an entry
        '''

        # TODO: lookup in list is not scalable.
        if await self.pos(member_id) is None:
            await self.add_member(member_id)

        mid = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))
        await self.kvcache.set(
            mid,
            {
                'member_id': str(member_id),
                'remote_addr': str(remote_addr),
                'schema_version': schema_version,
                'data_secret': data_secret,
                'last_seen': datetime.now(timezone.utc).isoformat(),
                'status': status.value,
            }
        )

    async def get_meta(self, member_id: UUID) -> dict:
        '''
        Get the metadata for a member

        :raises: KeyError if the member is not in the database
        '''

        mid = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))
        data = await self.kvcache.get(mid)

        if not data:
            raise KeyError(f'Member {str(member_id)} not found')

        value = {
            'member_id': UUID(data['member_id']),
            'remote_addr': ip_address(data['remote_addr']),
            'schema_version': int(data['schema_version']),
            'data_secret': data['data_secret'],
            'last_seen': datetime.fromisoformat(data['last_seen']),
            'status': MemberStatus[data['status']],
        }

        return value

    async def delete_meta(self, member_id: UUID) -> bool:
        '''
        Remove the metadata of a member from the DB

        :returns: whether the key existed or not
        '''

        mid = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))

        ret = await self.kvcache.delete(mid)

        exists = ret != 0

        if exists:
            _LOGGER.debug(f'Deleted the metadata for member {str(member_id)}')
        else:
            _LOGGER.debug(f'Member {str(member_id)} not found')

        return exists

    async def add_member(self, member_id: UUID) -> None:
        '''
        Adds a member to the end of the list of members
        '''

        _LOGGER.debug(f'Adding member f{member_id} to MEMBERS_LIST')
        await self.kvcache.push(MEMBERS_LIST, str(member_id))

    async def delete_members_list(self):
        '''
        Delete the list of members.

        :returns: whether the key existed or not
        '''

        ret = await self.kvcache.delete(MEMBERS_LIST)

        exists = ret != 0

        if exists:
            _LOGGER.debug('Deleted the list of members')
        else:
            _LOGGER.debug('List of members not found')

        return exists

    async def set_data(self, member_id: UUID, data: dict) -> bool:
        '''
        Saves the data for a member
        '''
        mid = MEMBER_ID_DATA_FORMAT.format(member_id=str(member_id))

        ret = await self.kvcache.set(mid, data)

        return ret

    async def get_data(self, member_id: UUID) -> dict:
        '''
        Get the data for a member

        :raises: KeyError if the member is not in the database
        '''

        mid = MEMBER_ID_DATA_FORMAT.format(member_id=str(member_id))
        data = await self.kvcache.get(mid)

        return data

    async def delete(self, member_id: UUID) -> bool:
        '''
        Remove the metadata of a member from the DB

        :returns: whether the key existed or not
        '''

        ret = await self.kvcache.delete(str(member_id))

        return ret != 0
