'''
ApiClient, base class for RestApiClient, and GqlApiClient
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from uuid import UUID
from enum import Enum
from copy import deepcopy
from typing import TypeVar
from datetime import datetime
from datetime import timezone
from urllib.parse import urlparse
from collections import namedtuple

import orjson

from httpx import Client as SyncHttpClient
from httpx import Response as HttpResponse
from httpx import AsyncClient as AsyncHttpClient
from httpx import RequestError
from httpx import TransportError
from httpx import TimeoutException


from byoda.secrets.account_secret import AccountSecret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.service_secret import ServiceSecret

from byoda.util.paths import Paths

from byoda.exceptions import ByodaRuntimeError

from byoda import config

_LOGGER = logging.getLogger(__name__)

Server = TypeVar('Server')
Network = TypeVar('Network')
Secret = TypeVar('Secret')


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


HttpSession = namedtuple('HttpClient', ['session', 'last_used'])

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

        self.host = parsed_url.hostname
        if (parsed_url.hostname.startswith('dir.')
                or parsed_url.hostname.startswith('proxy.')
                or network_name not in parsed_url.hostname):
            # For calls by Accounts and Services to the directory server,
            # to the proxy server, or servers not in the DNS domain of
            # the byoda network, we do not have to set the root CA as the
            # these use certs signed by a public CA
            ca_filepath = None
            _LOGGER.debug(
                'Not using byoda certchain for server cert '
                f'verification of {api}'
            )
        else:
            ca_filepath = storage.local_path + server.network.root_ca.cert_file
            _LOGGER.debug(f'Set server cert validation to {ca_filepath}')

        cert: tuple[str, str] | None = None
        if secret:
            if not storage:
                # Hack: podserver and svcserver use different attributes
                storage = server.storage_driver

            cert_filepath = storage.local_path + secret.cert_file
            key_filepath = secret.get_tmp_private_key_filepath()
            cert: tuple[str, str] | None = (cert_filepath, key_filepath)

            _LOGGER.debug(
                f'Setting client cert/key to {cert_filepath}, {key_filepath}'
            )

        if pool not in config.client_pools:
            self.session: AsyncHttpClient = AsyncHttpClient(
                timeout=timeout, verify=ca_filepath, cert=cert
            )

            config.client_pools[pool] = HttpSession(
                session=self.session, last_used=datetime.now(tz=timezone.utc)
            )
        else:
            self.session: HttpSession = config.client_pools[pool].session

    @staticmethod
    async def call(api: str, method: str | HttpMethod = 'GET', secret: Secret = None,
                   params: dict = None, data: dict = None, headers: dict = None,
                   service_id: int = None, member_id: UUID = None,
                   account_id: UUID = None, network_name: str = None,
                   port: int = None, timeout: int = 10):

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
        if method == 'GET':
            _LOGGER.debug(
                f'Calling {method} {api} with query parameters {params} '
                f'and data: {data}'
            )
        else:
            _LOGGER.debug(
                f'Calling {method} {api} with query parameters {params} '
            )

        client: ApiClient = ApiClient(
            api, secret=secret, service_id=service_id, network_name=network_name,
            timeout=timeout, port=port
        )

        try:
            resp: HttpResponse = await client.session.request(
                method, api, params=params, data=processed_data,
                headers=updated_headers
            )
        except (RequestError, TransportError, TimeoutException) as exc:
            raise ByodaRuntimeError(f'Error connecting to {api}: {exc}')

        if resp.status_code >= 400:
            raise ByodaRuntimeError(
                f'Failure to call API {api}: {resp.status}'
            )

        return resp

    @staticmethod
    async def close_all():
        '''
        Closes all AsyncHttpClient sessions to avoid warnings at the end of
        the calling program
        '''

        for pool, client in config.client_pools.items():
            await client.session.aclose()

        pools = list(config.client_pools.keys())
        for pool in pools:
            del config.client_pools[pool]

        config.client_pools: dict[str, AsyncHttpClient] = {}

    @staticmethod
    def _get_sync_client(api: str, secret: Secret, service_id: int,
                          timeout: int) -> SyncHttpClient:
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
            ca_filepath=None
            if not (api.startswith('https://dir')
                    or api.startswith('https://proxy')):
                ca_filepath = (
                    storage.local_path + server.network.root_ca.cert_file
                )
                _LOGGER.debug(f'Set server cert validation to {ca_filepath}')

            cert = None
            if secret:
                if not storage:
                    # Hack: podserver and svcserver use different attributes
                        storage = server.storage_driver

                cert_filepath = storage.local_path + secret.cert_file
                key_filepath = secret.get_tmp_private_key_filepath()

                _LOGGER.debug(
                    f'Setting client cert/key to {cert_filepath}, {key_filepath}'
                )
                cert = (cert_filepath, key_filepath)

            client = SyncHttpClient(timeout=timeout, verify=ca_filepath,cert=cert)
            config.sync_client_pools[pool] = client
        else:
            client: SyncHttpClient = config.sync_client_pools[pool]

        return client

    @staticmethod
    def call_sync(api: str, method: str = 'GET', secret:Secret = None,
                  params: dict = None, data: dict = None, headers: dict = None,
                  service_id: int = None, member_id: UUID = None,
                  account_id: UUID = None, network_name: str = None,
                  port: int = 443, timeout: int = 10) -> HttpResponse:

        server: Server = config.server

        client: SyncHttpClient = ApiClient._get_sync_client(
            api, secret, service_id, timeout
        )

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

        resp: HttpResponse = client.request(
            method, api, params=params, data=processed_data,
            headers=updated_headers,
        )

        return resp
