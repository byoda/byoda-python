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

from byoda.secrets import Secret
from byoda.secrets import AccountSecret
from byoda.secrets import MemberSecret
from byoda.secrets import ServiceSecret

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
                _LOGGER.debug(
                    f'Setting client cert/key to {secret.cert_file}, {key_path}'
                )
                self.session.cert = (secret.cert_file, key_path)
            else:
                self.session.cert = None

            self.session.verify = True
            if service_id is not None or isinstance(secret, MemberSecret):
                # For calls by Accounts and Services to the directory server,
                # we do not have to set the root CA as the directory server
                # uses a Let's Encrypt cert
                self.session.verify = server.network.root_ca.cert_file

            config.client_pools[type(secret)] = self.session
        else:
            self.session = config.client_pools[type(secret)]

    @staticmethod
    def call(api: str, method: str = 'GET', secret:Secret = None, params: Dict = None,
             data: Dict = None, service_id: int = None, member_id: UUID = None,
             account_id: UUID = None, network_name: str = None) -> requests.Response:

        '''
        Calls an API using the right credentials and accepted CAs
        '''

        # This is used by the bootstrap of the pod, when the global variable is not yet
        # set
        if not network_name:
            network = config.server.network
            network_name = network.name

        client = ApiClient(secret=secret, service_id=service_id)

        api = Paths.resolve(
            api, network_name, service_id=service_id, member_id=member_id,
            account_id=account_id
        )
        _LOGGER.debug(
            f'Calling {method} {api} with query parameters {params} '
            f'with root CA file: {client.session.verify} and data: {data} '
        )
        response = client.session.request(
            method, api, params=params, json=data
        )

        return response
