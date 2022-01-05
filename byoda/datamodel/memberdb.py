'''
Class MemberDb stores information for the Service and Directory servers
about registered clients

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
import json
from uuid import UUID
from typing import Dict
from datetime import datetime

from byoda.datatypes import MemberStatus

from byoda.datacache import KVCache

_LOGGER = logging.getLogger(__name__)

MEMBERS_LIST = 'members'


class MemberDb():
    '''
    Store for registered members
    '''

    def __init__(self, connection_string: str):
        '''
        Initializes the DB
        '''

        self.driver = KVCache.create(connection_string)

    def add(self, member_id: UUID, remote_addr: str, schema_version,
            data_secret: str, status: MemberStatus):
        '''
        Adds (or overwrites) an entry
        '''

        if not self.driver.exists(member_id):
            self.driver.push(MEMBERS_LIST, str(member_id))

        self.set(member_id, {
                'member_id': str(member_id),
                'remote_addr': remote_addr,
                'schema_version': schema_version,
                'data_secret': data_secret,
                'last_seen': datetime.utcnow().isoformat(),
                'status': status.value
            }
        )

    def delete(self, member_id: UUID) -> bool:
        '''
        Remove a member from the DB, if it is in it

        :returns: whether the key existed or not
        '''

        ret = self.driver.delete(member_id)

        return ret != 0
