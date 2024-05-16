'''
Class AssetDb stores information for the Service and Directory servers
about registered clients

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from uuid import UUID
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger
from datetime import datetime
from datetime import timezone
from ipaddress import IPv4Address
from ipaddress import ip_address

from byoda.datatypes import MemberStatus

from byoda.datacache.kv_cache import KVCache

_LOGGER: Logger = getLogger(__name__)

Member = TypeVar('Member')

ASSETS_LIST = 'assets'
ASSET_ID_META_FORMAT = '{asset_id}-meta'
ASSET_ID_DATA_FORMAT = '{asset_id}-data'


class AssetDb:
    '''
    Store for assets

    The metadata of a asset is stored in the ASSET_ID_META_FORMAT
    ('{asset_id}-meta) while the actual data is stored using the asset_id
    string as key
    '''

    def __init__(self, connection_string: str, service_id: int,
                 network_name: str, server_type: str) -> None:
        '''
        Initializes the DB. The DB consists of both a list of asset_ids,
        a hash of the metadata for each member_id and a hash of the actual
        data for the member
        '''

        self.kvcache = KVCache.create(
            connection_string, service_id=service_id,
            network_name=network_name, server_type=server_type)

        self._service_id: int = service_id

    @property
    def service_id(self) -> int:
        return self.kvcache.service_id

    @service_id.setter
    def service_id(self, service_id: int) -> None:
        self.kvcache.identifier = f'service-{str(service_id)}'

    def exists(self, member_id: UUID) -> bool:
        '''
        Checks if a member is already in the member-meta hash. This function
        does not check whether the member_id is in the list
        '''

        mid: str = ASSET_ID_META_FORMAT.format(member_id=str(member_id))

        exists: bool = self.kvcache.exists(mid)

        return exists

    def pos(self, member_id: UUID) -> int | None:
        '''
        Finds the first occurrence of value in the list for the key
        '''

        return self.kvcache.pos(ASSETS_LIST, str(member_id))

    def get_next(self, timeout: int = 0) -> UUID:
        '''
        Remove the first item in the ASSETS_LIST and return it
        '''

        value = self.kvcache.get_next(ASSETS_LIST, timeout=timeout)

        if isinstance(value, bytes):
            value = UUID(value.decode('utf-8'))

        return value

    def add_meta(self, member_id: UUID, remote_addr: IPv4Address,
                 schema_version: int, data_secret: str,
                 status: MemberStatus) -> None:
        '''
        Adds (or overwrites) an entry
        '''

        # TODO: lookup in list is not scalable.
        if self.pos(member_id) is None:
            self.add_member(member_id)

        mid: str = ASSET_ID_META_FORMAT.format(member_id=str(member_id))
        self.kvcache.set(mid, {
                'member_id': str(member_id),
                'remote_addr': str(remote_addr),
                'schema_version': schema_version,
                'data_secret': data_secret,
                'last_seen': datetime.now(timezone.utc).isoformat(),
                'status': status.value,
            }
        )

    def get_meta(self, member_id: UUID) -> dict:
        '''
        Get the metadata for a member

        :raises: KeyError if the member is not in the database
        '''

        mid: str = ASSET_ID_META_FORMAT.format(member_id=str(member_id))
        data: dict = self.kvcache.get(mid)

        if not data:
            raise KeyError(f'Member {str(member_id)} not found')

        value: dict[str, any] = {
            'member_id': UUID(data['member_id']),
            'remote_addr': ip_address(data['remote_addr']),
            'schema_version': int(data['schema_version']),
            'data_secret': data['data_secret'],
            'last_seen': datetime.fromisoformat(data['last_seen']),
            'status': MemberStatus[data['status']],
        }

        return value

    def delete_meta(self, member_id: UUID) -> bool:
        '''
        Remove the metadata of a member from the DB

        :returns: whether the key existed or not
        '''

        mid: str = ASSET_ID_META_FORMAT.format(member_id=str(member_id))

        ret = self.kvcache.delete(mid)

        exists: bool = ret != 0

        if exists:
            _LOGGER.debug(f'Deleted the metadata for member {str(member_id)}')
        else:
            _LOGGER.debug(f'Member {str(member_id)} not found')

        return exists

    def add_member(self, member_id: UUID) -> None:
        '''
        Adds a member to the end of the list of members
        '''

        _LOGGER.debug(f'Adding member f{member_id} to ASSETS_LIST')
        self.kvcache.push(ASSETS_LIST, str(member_id))

    def delete_ASSETS_LIST(self):
        '''
        Delete the list of members.

        :returns: whether the key existed or not
        '''

        ret = self.kvcache.delete(ASSETS_LIST)

        exists = ret != 0

        if exists:
            _LOGGER.debug('Deleted the list of members')
        else:
            _LOGGER.debug('List of members not found')

        return exists

    def set_data(self, member_id: UUID, data: dict) -> bool:
        '''
        Saves the data for a member
        '''
        mid = ASSET_ID_DATA_FORMAT.format(member_id=str(member_id))

        ret = self.kvcache.set(mid, data)

        return ret

    def get_data(self, member_id: UUID) -> dict:
        '''
        Get the data for a member

        :raises: KeyError if the member is not in the database
        '''

        mid = ASSET_ID_DATA_FORMAT.format(member_id=str(member_id))
        data = self.kvcache.get(mid)

        return data

    def delete(self, member_id: UUID) -> bool:
        '''
        Remove the metadata of a member from the DB

        :returns: whether the key existed or not
        '''

        ret = self.kvcache.delete(str(member_id))

        return ret != 0
