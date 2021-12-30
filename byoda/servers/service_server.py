'''
Class ServiceServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
import json
from uuid import UUID
from typing import TypeVar, Dict
from byoda.storage.filestorage import FileMode

from .server import Server
from .server import ServerType

from byoda import config

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')
RegistrationStatus = TypeVar('RegistrationStatus')


class ServiceServer(Server):
    def __init__(self):
        super().__init__()

        self.server_type = ServerType.Service

        # Dict with  as key the member ID and as value a
        # dict with keys 'member_id', 'remote_addr', 'schema_version'
        # and 'data_secret'

        self.member_db: MemberDb = MemberDb()

    def load_secrets(self, password: str = None):
        '''
        Loads the secrets used by the directory server
        '''

        self.service.load_secrets(with_private_key=True, password=password)


class MemberDb():
    '''
    Store for registered members
    '''

    def __init__(self, filepath: str = None):
        '''
        Initializes the DB
        '''

        self.filepath: str = filepath
        self.data: Dict[str: Dict] = dict()

    def load(self, filepath: str = None):
        '''
        Read the database
        '''

        if filepath:
            self.filepath = filepath

        if not self.filepath:
            raise ValueError('file path to load from has not been set')

        service = config.server.service
        try:
            data = service.storage_driver.read(self.filepath, FileMode.TEXT)
            self.data = json.loads(data)
        except FileNotFoundError:
            _LOGGER.info(f'MemberDB file does not exist: {self.filepath}')

    def save(self):
        '''
        Write the database
        '''

        if not self.filepath:
            raise ValueError('file path to save to has not been set')

        service = config.server.service
        service.storage_driver.write(
            self.filepath, json.dumps(self.data, indent=4, sort_keys=True),
            FileMode.TEXT
        )

    def add(self, member_id: UUID, remote_addr: str, schema_version,
            data_secret: str):
        '''
        Adds (or overwrites) an entry
        '''
        self.data[str(member_id)] = {
            'member_id': str(member_id),
            'remote_addr': remote_addr,
            'schema_version': schema_version,
            'data_secret': data_secret
        }

        self.save()

    def delete(self, member_id: UUID):
        '''
        Remove a member from the DB, if it is in it
        '''

        self.data.pop(str(member_id), None)

        self.save()
