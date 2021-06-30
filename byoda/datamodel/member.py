'''
Class for modeling an account on a network

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
import json
from typing import TypeVar

from byoda.util.secrets import MemberSecret, MemberDataSecret


_LOGGER = logging.getLogger(__name__)

Account = TypeVar('Account', bound='Account')
Service = TypeVar('Service', bound='Service')
Network = TypeVar('Network', bound='Network')


class Member:
    '''
    Class for modelling an Membership.

    This class is expected to only be used in the podserver
    '''

    def __init__(self, service_id: int, account: Account) -> None:
        '''
        Constructor
        '''

        self.member_id = None
        self.service_id = service_id
        self.account = account

        self.storage_driver = account.storage_driver

        paths = account.paths
        self.member_path = paths.get(paths.MEMBER_DIR, service_id=service_id)

        self.private_key_password = account.private_key_password
        self.secret = MemberSecret(service_id, self.paths)
        self.secret.load(
            with_private_key=True, password=self.private_key_password
        )
        self.member_secret.load(password=self.private_key_password)

        self.member_path = paths.member

        self.data_secret = MemberDataSecret(service_id, self.paths)
        self.data_secret.load(
            with_private_key=True, password=self.private_key_password
        )

        service_file = paths.get(
            paths.MEMBER_SERVICE_FILE, service_id=service_id
        )
        service_description = self.storage_driver.get(service_file)

        self.service_schema = json.loads(service_description)
