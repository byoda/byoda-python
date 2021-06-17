'''
Class for modeling an account on a network

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import logging
import json
from typing import TypeVar

from byoda.util import config


from byoda.storage.filestorage import FileStorage

from byoda.util.secrets import MemberSecret


_LOGGER = logging.getLogger(__name__)


Account = TypeVar('Account', bound='Account')
Service = TypeVar('Service', bound='Service')
Network = TypeVar('Network', bound='Network')


class Member:
    '''
    Class for modelling an account.

    This class is expected to only be used in the podserver
    '''

    def __init__(self, account: Account, service: Service) -> None:
        '''
        Constructor
        '''

        self.member_id = None
        self.service = Service
        self.account = Account

        paths = account.paths

        self.member_secret = MemberSecret(paths)
        self.private_key_password = account.private_key_password
        self.member_secret.load(password=self.private_key_password)

        self.member_path = paths.member

        for directory in os.listdir(paths.get(paths.ACCOUNT_DIR)):
            if not directory.startswith('service-'):
                continue
            service_id = directory[8:]
            self.member_secrets[service] = MemberSecret(
                service, self.paths
            )
            self.member_secrets[service].load(
                with_private_key=True, password=self.private_key_password
            )
