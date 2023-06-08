'''
ApiClient, base class for RestApiClient, and GqlApiClient
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
import asyncio

from uuid import UUID
from enum import Enum
from copy import deepcopy
from typing import TypeVar
from urllib.parse import urlparse

import orjson
import aiohttp
import ssl

from datetime import datetime
from datetime import timezone
from collections import namedtuple

import requests

from byoda.secrets.secret import Secret
from byoda.secrets.account_secret import AccountSecret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.service_secret import ServiceSecret

from byoda.util.paths import Paths

from byoda.exceptions import ByodaRuntimeError

from byoda import config

_LOGGER = logging.getLogger(__name__)

Server = TypeVar('Server')
Network = TypeVar('Network')

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


HttpSession = namedtuple('HttpSession', ['session', 'last_used'])

class ApiClient:
    '''
    Base class taking care of client credentials, accepted CA and some
    misc. settings (ie. 'timeout')
    '''

    def __init__(self, api: str, secret: Secret = None, service_id: int = None,
                 timeout: int = 10, port: int = None, network_name: str = None):
        '''
        Maintains a pool of connections for different destinations

        :raises: ValueError is service_id is specified for a secret that
        is not a MemberSecret
        '''

        server: Server = config.server

        if hasattr(server, 'local_storage'):
            storage = server.local_storage
        else:
            storage = None

        self.port = port

        parsed_url = urlparse(api)
        # We maintain a cache of sessions based on the authentication
        # requirements of the remote host and whether to use for verifying
        # the TLS server cert the root CA of the network or the regular CAs.
        self.session = None
        if not secret:
            if not port:
                if parsed_url.scheme == f'http-{parsed_url.hostname}':
                    self.port = 80
                    pool = f'noauth-http-{parsed_url.hostname}'
                else:
                    pool = f'noauth-https-{parsed_url.hostname}'
                    self.port = 443

        elif isinstance(secret, ServiceSecret):
            pool = f'service-{service_id}-{parsed_url.hostname}'
        elif isinstance(secret, MemberSecret):
            pool = f'member-{parsed_url.hostname}'
        elif isinstance(secret, AccountSecret):
            pool = f'account-{parsed_url.hostname}'
        else:
            raise ValueError(
                'Secret must be either an account-, member- or '
                f'service-secret, not {type(secret)}'
            )

        self.ssl_context = None

        self.host = parsed_url.hostname
        if (parsed_url.hostname.startswith('dir.')
                or parsed_url.hostname.startswith('proxy.')
                or network_name not in parsed_url.hostname):
            # For calls by Accounts and Services to the directory server,
            # to the proxy server, or servers not in the DNS domain of
            # the byoda network, we do not have to set the root CA as the
            # these use certs signed by a public CA
            _LOGGER.debug(
                'Not using byoda certchain for server cert '
                f'verification of {api}'
            )
            self.ssl_context = ssl.create_default_context()
        else:
            ca_filepath = storage.local_path + server.network.root_ca.cert_file

            self.ssl_context = config.ssl_contexts.get(pool)
            if not self.ssl_context:
                self.ssl_context = ssl.create_default_context(cafile=ca_filepath)
                config.ssl_contexts[pool] = self.ssl_context

            _LOGGER.debug(f'Set server cert validation to {ca_filepath}')

        if secret:
            if not storage:
                # Hack: podserver and svcserver use different attributes
                storage = server.storage_driver

            cert_filepath = storage.local_path + secret.cert_file
            key_filepath = secret.get_tmp_private_key_filepath()

            _LOGGER.debug(
                f'Setting client cert/key to {cert_filepath}, {key_filepath}'
            )
            self.ssl_context.load_cert_chain(cert_filepath, key_filepath)

        if pool not in config.client_pools:
            timeout_setting = aiohttp.ClientTimeout(total=timeout)
            self.session = aiohttp.ClientSession(timeout=timeout_setting)

            # TODO: create podworker job to prune old sessions
            config.client_pools[pool] = HttpSession(
                session=self.session, last_used=datetime.now(tz=timezone.utc)
            )
        else:
            self.session: aiohttp.ClientSession = config.client_pools[pool].session

    @staticmethod
    async def call(api: str, method: str | HttpMethod = 'GET', secret:Secret = None,
                   params: dict = None, data: dict = None, headers: dict = None,
                   service_id: int = None, member_id: UUID = None,
                   account_id: UUID = None, network_name: str = None,
                   port: int = None, timeout: int = 10) -> aiohttp.ClientResponse:

        '''
        Calls an API using the right credentials and accepted CAs

        Either the secret must be the secret of the pod (or test case) or
        the headers need to include an Authentication header with a valid JWT
        '''

        server: Server = config.server

        # This is used by the bootstrap of the pod, when the global variable is not yet
        # set
        if not network_name:
            network: Network = server.network
            network_name: str = network.name

        if isinstance(method, HttpMethod):
            method: str = method.value

        processed_data = data
        updated_headers = None
        if data and type(data) not in [str, bytes]:
            # orjson can serialize datetimes, UUIDs
            processed_data = orjson.dumps(data)
            if headers:
                updated_headers = deepcopy(headers)
            else:
                updated_headers = {}
            updated_headers['Content-Type'] = 'application/json'

        api = Paths.resolve(
            api, network_name, service_id=service_id, member_id=member_id,
            account_id=account_id
        )
        _LOGGER.debug(
            f'Calling {method} {api} with query parameters {params} '
            f'and data: {data}'
        )

        client = ApiClient(
            api, secret=secret, service_id=service_id, network_name=network_name
        )

        try:
            response: aiohttp.ClientResponse = await client.session.request(
                method, api, params=params, data=processed_data,
                headers=updated_headers, ssl=client.ssl_context, timeout=timeout
            )
        except (aiohttp.ServerTimeoutError, aiohttp.ServerConnectionError,
                aiohttp.client_exceptions.ClientConnectorCertificateError,
                aiohttp.client_exceptions.ClientConnectorError,
                asyncio.exceptions.TimeoutError) as exc:
            raise ByodaRuntimeError(f'Error connecting to {api}: {exc}')

        if response.status >= 400:
            raise ByodaRuntimeError(
                f'Failure to call API {api}: {response.status}'
            )

        return response

    @staticmethod
    async def close_all():
        '''
        Closes all aiohttp sessions to avoid warnings at the end of the calling program
        '''

        for pool, httpsession in config.client_pools.items():
            await httpsession.session.close()

        pools = list(config.client_pools.keys())
        for pool in pools:
            del config.client_pools[pool]

        config.client_pools: dict[str, aiohttp.ClientSession] = {}

    @staticmethod
    def _get_sync_session(api: str, secret: Secret, service_id: int,
                          timeout: int):
        server: Server = config.server
        if hasattr(server, 'local_storage'):
            storage = server.local_storage
        else:
            storage = None

        if not secret:
            if api.startswith('http://'):
                pool = 'noauth-http'
            else:
                pool = 'noauth-https'
        elif isinstance(secret, ServiceSecret):
            if service_id is None:
                raise ValueError(
                    'Can not use service secret for M-TLS if service_id is '
                    'not specified'
                )
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

        if pool not in config.sync_client_pools:
            session = requests.Session()
            session.timeout = timeout

            if not (api.startswith('https://dir')
                    or api.startswith('https://proxy')):
                session.verify = (
                    storage.local_path + server.network.root_ca.cert_file
                )
                _LOGGER.debug(f'Set server cert validation to {session.verify}')

            if secret:
                if not storage:
                    # Hack: podserver and svcserver use different attributes
                        storage = server.storage_driver

                cert_filepath = storage.local_path + secret.cert_file
                key_filepath = secret.get_tmp_private_key_filepath()

                _LOGGER.debug(
                    f'Setting client cert/key to {cert_filepath}, {key_filepath}'
                )
                session.cert = (cert_filepath, key_filepath)


            config.sync_client_pools[pool] = session
        else:
            session = config.sync_client_pools[pool]

        return session

    @staticmethod
    def call_sync(api: str, method: str = 'GET', secret:Secret = None,
                  params: dict = None, data: dict = None, headers: dict = None,
                  service_id: int = None, member_id: UUID = None,
                  account_id: UUID = None, network_name: str = None,
                  port: int = 443, timeout: int = 10) -> requests.Response:

        server: Server = config.server

        session = ApiClient._get_sync_session(api, secret, service_id, timeout)

        if not network_name:
            network = server.network
            network_name = network.name

        if type(data) not in [str, bytes]:
            # orjson can serialize datetimes, UUIDs
            processed_data = orjson.dumps(data)
            if headers:
                updated_headers = deepcopy(headers)
            else:
                updated_headers = {}

            updated_headers['Content-Type'] = 'application/json'

        if isinstance(method, HttpMethod):
            method = method.value

        api = Paths.resolve(
            api, network_name, service_id=service_id, member_id=member_id,
            account_id=account_id
        )

        response = session.request(
            method, api, params=params, data=processed_data,
            headers=updated_headers,
        )

        return response
