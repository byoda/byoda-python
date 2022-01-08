'''
Class ServiceServer derived from Server class for modelling
a server that hosts a BYODA Service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import TypeVar

from byoda.datastore import MemberDb

from byoda.datatypes import ServerType

from .server import Server


_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')
RegistrationStatus = TypeVar('RegistrationStatus')


class ServiceServer(Server):
    def __init__(self, network: Network, connection_string: str):
        super().__init__(network)

        self.server_type = ServerType.SERVICE

        self.member_db: MemberDb = MemberDb(connection_string)

    def load_secrets(self, password: str = None):
        '''
        Loads the secrets used by the directory server
        '''

        self.service.load_secrets(with_private_key=True, password=password)
