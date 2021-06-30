'''
Class for modeling an account on a network

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import logging
from typing import TypeVar

from .member import Member
from byoda.util.secrets import AccountSecret
from byoda.util.secrets import AccountDataSecret


_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')
Service = TypeVar('Service', bound='Service')


class Account:
    '''
    Class for modelling an account.

    This class is expected to only be used in the podserver
    '''

    def __init__(self, account_id: str, network: Network):
        '''
        Constructor
        '''

        self.account_id = account_id
        self.memberships = dict()

        self.network = network

        paths = self.paths
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
            service_id = directory[8:]

            self.add_membership(service_id=service_id)

    def add_membership(self, service_id: int) -> Member:
        '''
        Add the membership of a service to the account
        '''

        if service_id in self.memberships:
            raise ValueError(
                f'Already a member of service {service_id}'
            )

        member = Member(service_id, self)

        self.memberships[service_id] = member

    def join(self, service: Service) -> Member:
        '''
        Join a service for the first time
        '''

        raise NotImplementedError
