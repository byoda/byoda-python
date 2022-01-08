'''
Class MemberDb stores information for the Service and Directory servers
about registered clients

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from uuid import UUID
from datetime import datetime
from typing import TypeVar, Dict
from ipaddress import ip_address

from byoda.datamodel.schema import Schema
from byoda.datatypes import MemberStatus

from byoda.datacache import KVCache

_LOGGER = logging.getLogger(__name__)

Member = TypeVar('Member')

MEMBERS_LIST = 'members'
MEMBER_ID_META_FORMAT = '{member_id}-meta'
MEMBER_ID_DATA_FORMAT = '{member_id}-data'


class MemberDb():
    '''
    Store for registered members

    The metadata of a member is stored in the MEMBER_ID_META_FORMAT
    ('{member_id}-meta) while the actual data is stored using the member_id
    string as key
    '''

    def __init__(self, connection_string: str, schema: Schema = None):
        '''
        Initializes the DB. The DB consists of both a list of member_ids,
        a hash of the metadata for each member_id and a hash of the actual
        data for the member
        '''

        self.driver = KVCache.create(connection_string)
        self.schema = schema

    def exists(self, member_id: UUID) -> bool:
        '''
        Checks if a member is already in the member-meta hash. This function
        does not check whether the member_id is in the list
        '''

        mid = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))
        exists = self.driver.exists(mid)

        return exists

    def get_next(self):
        '''
        Get the next member in the queue
        '''

        self.driver.shift_push_list()
        
    def add_meta(self, member_id: UUID, remote_addr: str, schema_version,
                 data_secret: str, status: MemberStatus):
        '''
        Adds (or overwrites) an entry
        '''

        if not self.exists(member_id):
            self.driver.push(MEMBERS_LIST, str(member_id))

        mid = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))
        self.driver.set(mid, {
                'member_id': str(member_id),
                'remote_addr': remote_addr,
                'schema_version': schema_version,
                'data_secret': data_secret,
                'last_seen': datetime.utcnow().isoformat(),
                'status': status.value,
            }
        )

    def get_meta(self, member_id: UUID) -> dict:
        '''
        Get the metadata for a member

        :raises: KeyError if the member is not in the database
        '''

        mid = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))
        data = self.driver.get(mid)

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

    def delete_meta(self, member_id: UUID) -> bool:
        '''
        Remove the metadata of a member from the DB

        :returns: whether the key existed or not
        '''

        mid = MEMBER_ID_META_FORMAT.format(member_id=str(member_id))

        ret = self.driver.delete(mid)

        return ret != 0

    def set_data(self, member_id: UUID, data: Dict) -> bool:
        '''
        Saves the data for a member
        '''
        mid = MEMBER_ID_DATA_FORMAT.format(member_id=str(member_id))

        ret = self.driver.set(mid, data)

        return ret

    def get_data(self, member_id: UUID) -> dict:
        '''
        Get the data for a member

        :raises: KeyError if the member is not in the database
        '''

        mid = MEMBER_ID_DATA_FORMAT.format(member_id=str(member_id))
        data = self.driver.get(mid)

        return data

    def delete(self, member_id: UUID) -> bool:
        '''
        Remove the metadata of a member from the DB

        :returns: whether the key existed or not
        '''

        ret = self.driver.delete(str(member_id))

        return ret != 0
