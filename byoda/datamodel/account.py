'''
Class for modeling an account on a network

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import logging
from typing import TypeVar

from byoda.util.secrets import AccountSecret
from byoda.util.secrets import AccountDataSecret
from byoda.util.secrets import MemberSecret
from byoda.util.secrets import MemberDataSecret


_LOGGER = logging.getLogger(__name__)


Network = TypeVar('Network', bound='Network')


class Account:
    '''
    Class for modelling an account.

    This class is expected to only be used in the podserver
    '''

    def __init__(self, account_id: str, network: Network) -> None:
        '''
        Constructor
        '''

        self.account_id = account_id

        paths = network.paths
        paths.account = 'pod'
        self.account_path = paths.account

        self.private_key_password = network.private_key_password

        self.account_secret = AccountSecret(paths)
        self.account_secret.load(password=self.private_key_password)

        self.account_data_secret = AccountDataSecret(paths)
        self.account_data_secret.load(password=self.private_key_password)

        for directory in os.listdir(paths.get(paths.ACCOUNT_DIR)):
            if not directory.startswith('service-'):
                continue
            service = directory[8:]
            self.member_secrets[service] = MemberSecret(
                service, self.paths
            )
            self.member_secrets[service].load(
                with_private_key=True, password=self.private_key_password
            )

            self.member_data_secrets[service] = MemberDataSecret(
                service, self.paths
            )
