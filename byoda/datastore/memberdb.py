'''
Class MemberDb stores information for the Service and Directory servers
about registered clients

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from uuid import UUID
from typing import Self
from typing import TypeVar
from logging import getLogger
from datetime import datetime
from datetime import timezone
from ipaddress import ip_address
from ipaddress import IPv4Address

from byoda.datatypes import MemberStatus
from byoda.datatypes import CacheTech
from byoda.datatypes import CacheType

from byoda.datacache.kv_cache import KVCache

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)

Member = TypeVar('Member')

MEMBERS_LIST = 'members'
MEMBER_ID_META_FORMAT = '{member_id}-meta'
MEMBER_ID_DATA_FORMAT = '{member_id}-data'


class MemberDb:
    '''
    Store for registered members

    The metadata of a member is stored in the MEMBER_ID_META_FORMAT
    ('{member_id}-meta') while the actual data is stored using the member_id
    string as key
    '''

    def __init__(self, service_id: int, network_name: str) -> None:
        '''
        Do not call this constructor directly. Use MemberDb.setup() instead

        :param schema: the schema to use for validation of the data
        :returns: self
        :raises: (none)
        '''

        self._service_id: int = service_id
        self.network_name: str = network_name
        self.kvcache: KVCache | None = None

    async def setup(connection_string: str, service_id: int, network_name: str
                    ) -> Self:
        '''
        Factory for the MemberDB class

        :param connection_string:
        :param schema: the schema to use for validation of the data
        '''

        self = MemberDb(service_id, network_name)
        kvcache: KVCache = await KVCache.create(
            connection_string, service_id=service_id,
            network_name=network_name, server_type='ServiceServer',
            cache_type=CacheType.MEMBERDB, cache_tech=CacheTech.REDIS
        )

        self.kvcache = kvcache

        return self

    async def close(self) -> None:
        '''
        Close the DB
        '''

        await self.kvcache.close()

    @property
    def service_id(self):
        kvcache: KVCache = self.kvcache
        return kvcache.identifier

    @service_id.setter
    def service_id(self, service_id: int) -> None:
        kvcache: KVCache = self.kvcache
        kvcache.identifier = f'service-{str(service_id)}'

    async def exists(self, member_id: UUID) -> bool:
        '''
        Checks if a member is already in the member-meta hash. This function
        does not check whether the member_id is in the list
        '''

        mid: str = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))

        kvcache: KVCache = self.kvcache
        exists: bool = await kvcache.exists(mid)

        return exists

    async def pos(self, member_id: UUID):
        '''
        Finds the first occurrence of value in the list for the key
        '''

        kvcache: KVCache = self.kvcache
        return await kvcache.pos(MEMBERS_LIST, str(member_id))

    async def get_next(self, timeout: int = 0) -> UUID:
        '''
        Remove the first item in the MEMBER_LIST and return it
        '''

        kvcache: KVCache = self.kvcache
        value: str | bytes = await kvcache.get_next(MEMBERS_LIST, timeout=-1)

        if isinstance(value, bytes):
            value = UUID(value.decode('utf-8'))
        elif isinstance(value, str):
            value = UUID(value)

        return value

    async def add_meta(self, member_id: UUID, remote_addr: IPv4Address,
                       schema_version: int, data_secret: str,
                       status: MemberStatus) -> None:
        '''
        Adds (or overwrites) an entry
        '''

        log_data: dict[str, any] = {
            'member_id': str(member_id),
            'remote_addr': str(remote_addr),
            'member_status': status.name,
        }

        # TODO: lookup in list is not scalable.
        if await self.pos(member_id) is None:
            _LOGGER.debug('Adding member to the list', extra=log_data)
            await self.add_member(member_id)

        mid: str = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))
        log_data['member_meta_id'] = mid
        _LOGGER.debug(
            'Adding metadata for member to the MemberDB', extra=log_data
        )

        kvcache: KVCache = self.kvcache
        await kvcache.set(
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

        mid: str = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))
        kvcache: KVCache = self.kvcache
        data = await kvcache.get(mid)

        last_seen: datetime = datetime.fromisoformat(data['last_seen'])
        log_data: dict[str, any] = {
            'member_id': str(member_id),
            'member_meta_id': mid,
            'last_seen': last_seen,
        }
        _LOGGER.debug(
            'Got metadata for member with key from the MemberDB',
            extra=log_data
        )

        if not data:
            raise KeyError(f'Member {str(member_id)} not found')

        value: dict[str, any] = {
            'member_id': UUID(data['member_id']),
            'remote_addr': ip_address(data['remote_addr']),
            'schema_version': int(data['schema_version']),
            'data_secret': data['data_secret'],
            'last_seen': last_seen,
            'status': MemberStatus[data['status']],
        }

        return value

    async def delete_meta(self, member_id: UUID) -> bool:
        '''
        Remove the metadata of a member from the DB

        :returns: whether the key existed or not
        '''

        mid: str = MEMBER_ID_META_FORMAT.format(member_id=member_id)

        kvcache: KVCache = self.kvcache
        ret = await kvcache.delete(mid)

        exists = ret != 0

        log_data: dict[str, any] = {
            'member_id': member_id,
            'exists': exists,
        }
        if exists:
            _LOGGER.debug('Deleted the metadata for member', extra=log_data)
        else:
            _LOGGER.debug('Member not found', extra=log_data)

        return exists

    async def add_member(self, member_id: UUID) -> None:
        '''
        Adds a member to the end of the list of members
        '''

        _LOGGER.debug(
            'Adding member to MEMBERS_LIST',
            extra={'member_id': str(member_id)}
        )
        kvcache: KVCache = self.kvcache
        await kvcache.push(MEMBERS_LIST, str(member_id))

    async def get_members(self) -> list[UUID]:
        '''
        Get the list of members
        '''

        kvcache: KVCache = self.kvcache
        members: list[str] = await kvcache.get_list(MEMBERS_LIST)

        normalized_members: list[UUID] = []
        for member in members:
            member_val: UUID
            if isinstance(member, UUID):
                member_val = member
            elif isinstance(member, str):
                member_val = UUID(member)
            elif isinstance(member, bytes):
                member_val = UUID(member.decode('utf-8'))

            normalized_members.append(member_val)

        _LOGGER.debug(
            'Retrieved the list of members',
            extra={'members_count': len(normalized_members)}
        )

        return normalized_members

    async def delete_members_list(self) -> bool:
        '''
        Delete the list of members.

        :returns: whether the key existed or not
        '''

        kvcache: KVCache = self.kvcache
        ret: int = await kvcache.delete(MEMBERS_LIST)

        exists: bool = ret != 0

        if exists:
            _LOGGER.debug('Deleted the list of members')
        else:
            _LOGGER.debug('List of members not found')

        return exists

    async def set_data(self, member_id: UUID, data: dict) -> bool:
        '''
        Saves the data for a member

        :param member_id:
        :param data:
        :returns: whether key was set in the DB
        :raises: (none)
        '''

        mid: str = MEMBER_ID_DATA_FORMAT.format(member_id=str(member_id))

        kvcache: KVCache = self.kvcache
        ret = await kvcache.set(mid, data)

        return ret

    async def get_data(self, member_id: UUID) -> dict:
        '''
        Get the data for a member

        :raises: KeyError if the member is not in the database
        '''

        mid: str = MEMBER_ID_DATA_FORMAT.format(member_id=str(member_id))
        kvcache: KVCache = self.kvcache
        data: dict = await kvcache.get(mid)

        return data

    async def delete(self, member_id: UUID) -> bool:
        '''
        Remove the metadata of a member from the DB

        :returns: whether the key existed or not
        '''

        kvcache: KVCache = self.kvcache
        ret = await kvcache.delete(str(member_id))

        return ret != 0
