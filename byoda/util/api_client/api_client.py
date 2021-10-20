'''
ApiClient, base class for RestApiClient, and GqlApiClient
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging
from enum import Enum
from typing import Dict, ClassVar
from uuid import UUID

import requests

from byoda.util.secrets import Secret
from byoda.util.secrets import AccountSecret
from byoda.util.secrets import MemberSecret
from byoda.util.secrets import ServiceSecret

from byoda.util import Paths
from byoda import config

_LOGGER = logging.getLogger(__name__)


class ClientAuthType(Enum):
    # flake8: noqa=E221
    Account     = 0
    Member      = 1
    Service     = 2

config.client_pools = dict()


class ApiClient:
    '''
    Base class taking care of client credentials, accepted CA and some
    misc. settings (ie. 'timeout')
    '''

    def __init__(self, secret: Secret = None, service_id: int = None):
        '''
        Maintains a pool of connections for different destinations

        :raises: ValueError is service_id is specified for a secret that
        is not a MemberSecret
        '''

        server = config.server

        self.session = None
        if not secret:
            pool = 'noauth'
        elif isinstance(secret, ServiceSecret):
            pool = f'service-{service_id}'
        elif isinstance(secret, MemberSecret):
            pool = 'member'
        elif isinstance(secret, AccountSecret):
            pool = 'account'
        else:
            raise ValueError(
                'Secret must be either an account-, member- or '
                f'service-secret, not {type(secret)}'
            )

        if pool not in config.client_pools:
            self.session = requests.Session()
            self.session.timout = 3
            if secret:
                key_path = secret.save_tmp_private_key()
                self.session.cert = (secret.cert_file, key_path)
            else:
                self.session.cert = None

            if isinstance(secret, MemberSecret):
                self.session.verify = server.network.root_ca.cert_file()
        else:
            self.session = config.client_pools[type(secret)]

    @staticmethod
    def call(api: str, method: str, secret:Secret = None, params: Dict = None,
             data: Dict = None, service_id: int = None, member_id: UUID = None,
             account_id: UUID = None) -> requests.Response:

        '''
        Calls an API using the right credentials and accepted CAs
        '''

        network = config.server.network

        client = ApiClient(secret=secret, service_id=service_id)

        api = Paths.resolve(
            api, network.name, service_id=service_id, member_id=member_id,
            account_id=account_id
        )

        response = client.session.request(method, api, params=params, json=data)

        return response
