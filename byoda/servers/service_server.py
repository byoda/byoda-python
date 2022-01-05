'''
Class ServiceServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import TypeVar

from byoda.datamodel.memberdb import MemberDb

from .server import Server
from .server import ServerType

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')
RegistrationStatus = TypeVar('RegistrationStatus')


class ServiceServer(Server):
    def __init__(self, connection_string: str):
        super().__init__()

        self.server_type = ServerType.Service

        self.member_db: MemberDb = MemberDb(connection_string)

    def load_secrets(self, password: str = None):
        '''
        Loads the secrets used by the directory server
        '''

        self.service.load_secrets(with_private_key=True, password=password)
