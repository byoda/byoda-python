'''
ApiClient, base class for RestApiClient, and GqlApiClient
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import logging
from enum import Enum
from typing import Dict
from uuid import UUID

import aiohttp
import ssl

from byoda.secrets import Secret
from byoda.secrets import AccountSecret
from byoda.secrets import MemberSecret
from byoda.secrets import ServiceSecret
from byoda.servers.server import Server

from byoda.util.paths import Paths
from byoda import config

_LOGGER = logging.getLogger(__name__)


class ClientAuthType(Enum):
    # flake8: noqa=E221
    Account     = 0
    Member      = 1
    Service     = 2


class HttpMethod(Enum):
    # flake8: noqa=E221
    GET         = 'get'
    POST        = 'post'
    PUT         = 'put'
    PATCH       = 'patch'
    DELETE      = 'delete'
    HEAD        = 'head'

config.client_pools = dict()


class ApiClient:
    '''
    Base class taking care of client credentials, accepted CA and some
    misc. settings (ie. 'timeout')
    '''

    def __init__(self, api: str, secret: Secret = None, service_id: int = None,
                 timeout: int = 10, port: int = None):
        '''
        Maintains a pool of connections for different destinations

        :raises: ValueError is service_id is specified for a secret that
        is not a MemberSecret
        '''

        server: Server = config.server

        self.port = port

        # We maintain a cache of sessions based on the authentication
        # requirements of the remote host and whether to use for verifying
        # the TLS server cert the root CA of the network or the regular CAs.
        self.session = None
        if not secret:
            if not port:
                if api.startswith('http://'):
                    self.port = 80
                    pool = 'noauth-http'
                else:
                    pool = 'noauth-https'
                    self.port = 443

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

        self.ssl_context = None

        # HACK: disable client pools as it generates RuntimeError
        # for 'eventloop is already closed'
        if pool not in config.client_pools or True:
            if api.startswith('https://dir') or api.startswith('https://proxy'):
                # For calls by Accounts and Services to the directory server,
                # we do not have to set the root CA as the directory server
                # uses a Let's Encrypt cert
                _LOGGER.debug(
                    'No using byoda certchain for server cert '
                    f'verification of {api}'
                )
                self.ssl_context = ssl.create_default_context()
            else:
                filepath = (
                    server.network.paths._root_directory + '/' +
                    server.network.root_ca.cert_file
                )
                self.ssl_context = ssl.create_default_context(cafile=filepath)
                _LOGGER.debug(f'Set server cert validation to {filepath}')

            if secret:
                key_path = secret.save_tmp_private_key()
                cert_filepath = (
                    server.network.paths.root_directory + '/' + secret.cert_file
                )
                _LOGGER.debug(
                    f'Setting client cert/key to {cert_filepath}, {key_path}'
                )
                self.ssl_context.load_cert_chain(cert_filepath, key_path)

            timeout_setting = aiohttp.ClientTimeout(total=timeout)
            self.session = aiohttp.ClientSession(timeout=timeout_setting)

            config.client_pools[pool] = self.session
        else:
            self.session = config.client_pools[pool]

    @staticmethod
    async def call(api: str, method: str = 'GET', secret:Secret = None,
                   params: Dict = None, data: Dict = None, headers: Dict = None,
                   service_id: int = None, member_id: UUID = None,
                   account_id: UUID = None, network_name: str = None,
                   port: int = None, timeout: int = 10) -> aiohttp.ClientResponse:

        '''
        Calls an API using the right credentials and accepted CAs

        Either the secret must be the secret of the pod (or test case) or
        the headers need to include an Authentication header with a valid JWT
        '''

        # This is used by the bootstrap of the pod, when the global variable is not yet
        # set
        if not network_name:
            network = config.server.network
            network_name = network.name

        if isinstance(method, HttpMethod):
            method = method.value

        client = ApiClient(api, secret=secret, service_id=service_id)

        api = Paths.resolve(
            api, network_name, service_id=service_id, member_id=member_id,
            account_id=account_id
        )
        _LOGGER.debug(
            f'Calling {method} {api} with query parameters {params} '
            f'and data: {data}'
        )
        try:
            response: aiohttp.ClientResponse = await client.session.request(
                method, api, params=params, json=data, headers=headers,
                ssl=client.ssl_context, timeout=timeout
            )
        except (aiohttp.ServerTimeoutError, aiohttp.ServerConnectionError) as exc:
            raise RuntimeError(exc)

        await client.session.close()

        if response.status >= 400:
            raise RuntimeError(
                f'Failure to call API {api}: {response.status}'
            )

        return response
