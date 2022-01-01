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

    def __init__(self, api: str, secret: Secret = None, service_id: int = None):
        '''
        Maintains a pool of connections for different destinations

        :raises: ValueError is service_id is specified for a secret that
        is not a MemberSecret
        '''

        server = config.server

        # We maintain a cache of sessions based on the authentication
        # requirements of the remote host and whether to use for verifying
        # the TLS server cert the root CA of the network or the regular CAs.
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
            self.session.timeout = 3
            if secret:
                key_path = secret.save_tmp_private_key()
                cert_filepath = (
                    server.network.paths.root_directory() + '/' + secret.cert_file
                )
                _LOGGER.debug(
                    f'Setting client cert/key to {cert_filepath}, {key_path}'
                )
                self.session.cert = (cert_filepath, key_path)
            else:
                self.session.cert = None

            self.session.verify = True
            if api.startswith(f'https://dir'):
                # For calls by Accounts and Services to the directory server,
                # we do not have to set the root CA as the directory server
                # uses a Let's Encrypt cert
                self.session.verify = True
                _LOGGER.debug(
                    'Disabled using byoda certchain for server cert '
                    'verification'
                )
            else:
                filepath = (
                    server.network.paths._root_directory + '/' +
                    server.network.root_ca.cert_file
                )
                self.session.verify = filepath
                _LOGGER.debug(f'Set server cert validation to {filepath}')

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

        client = ApiClient(api, secret=secret, service_id=service_id)

        api = Paths.resolve(
            api, network_name, service_id=service_id, member_id=member_id,
            account_id=account_id
        )
        _LOGGER.debug(
            f'Calling {method} {api} with query parameters {params} '
            f'with root CA file: {client.session.verify} and data: {data} '
        )
        try:
            response = client.session.request(
                method, api, params=params, json=data
            )
        except (requests.exceptions.ConnectTimeout,
                requests.exceptions.ConnectionError) as exc:
            raise RuntimeError(exc)

        return response
