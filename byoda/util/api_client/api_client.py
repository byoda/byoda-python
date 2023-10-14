'''
ApiClient, base class for RestApiClient, and GqlApiClient
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import asyncio

from uuid import UUID
from enum import Enum
from copy import deepcopy
from typing import TypeVar
from random import random
from logging import getLogger
from datetime import datetime
from datetime import timezone
from urllib.parse import urlparse
from collections import namedtuple

import orjson

from fastapi import FastAPI

from ssl import SSLCertVerificationError

from httpx import Client as SyncHttpClient
from httpx import AsyncClient as AsyncHttpClient
from httpx import Response as HttpResponse
from httpx import RequestError
from httpx import TransportError

from opentelemetry.propagate import inject

from byoda.storage.filestorage import FileStorage
from byoda.secrets.account_secret import AccountSecret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.service_secret import ServiceSecret

from byoda.requestauth.jwt import JWT

from byoda.util.paths import Paths

from byoda.util.logger import Logger

from byoda.exceptions import ByodaRuntimeError

from byoda import config

_LOGGER: Logger = getLogger(__name__)

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
    OPTIONS     = 'options'


HttpSession = namedtuple('HttpClient', ['session', 'last_used'])

class ApiClient:
    MAX_RETRIES: int = 8
    RETRY_DELAYS: list [int] = [0.1, 1, 2, 4, 8, 16, 32, 64]

    '''
    Base class taking care of client credentials, accepted CA and some
    misc. settings (ie. 'timeout')
    '''

    def __init__(self, api: str, secret: Secret = None, jwt: JWT = None,
                 service_id: int = None, timeout: int = 10,
                 port: int = None, network_name: str = None,
                 app: FastAPI | None = None):
        '''
        Maintains a pool of connections for different destinations

        :param api: URL of the API to call
        :param secret: secret to use as client for M-TLS authentication
        :param service_id: service_id to use for M-TLS authentication
        :param timeout: timeout for the HTTP call
        :param port: port to use for the HTTP call
        :param network_name: name of the network to use for the HTTP call
        :param app: FastAPI app to use for the HTTP call, only to be used
        for test cases
        :returns: (none)
        :raises: ValueError
        '''

        self.session: AsyncHttpClient
        self.host: str
        self.pool: str

        self.timeout: int = timeout
        self.port: int = port
        self.cert: tuple[str, str] | None = None
        self.ca_filepath: str | None = None
        self.headers: dict[str, str] = {}
        self.app: FastAPI | None = app

        if secret and jwt:
            raise ValueError(
                'Specify either secret or JWT to use for authentication'
            )
        # HACK: fix this hack
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
        if not secret:
            if not port:
                if parsed_url.scheme == f'http-{parsed_url.hostname}':
                    self.port = 80
                    self.pool = f'noauth-http-{parsed_url.hostname}'
                else:
                    self.pool = f'noauth-https-{parsed_url.hostname}'
                    self.port = 443

        elif isinstance(secret, ServiceSecret):
            self.pool = f'service-{service_id}-{parsed_url.hostname}'
        elif isinstance(secret, MemberSecret):
            self.pool = f'member-{parsed_url.hostname}'
        elif isinstance(secret, AccountSecret):
            self.pool = f'account-{parsed_url.hostname}'
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
            _LOGGER.debug(
                'Not using byoda certchain for server cert '
                f'verification of {api}'
            )
        else:
            self.ca_filepath = (
                storage.local_path + server.network.root_ca.cert_file
            )
            _LOGGER.debug(f'Set server cert validation to {self.ca_filepath}')

        if config.debug and parsed_url.hostname.endswith(network_name):
            # For tracing propagate the Span ID to remote hosts
            inject(self.headers)

        if secret:
            if not storage:
                # HACK: podserver and svcserver use different attributes
                storage = server.storage_driver

            cert_filepath: str = storage.local_path + secret.cert_file
            key_filepath: str = secret.get_tmp_private_key_filepath()
            self.cert = (cert_filepath, key_filepath)

            _LOGGER.debug(
                f'Setting client cert/key to {cert_filepath}, {key_filepath}'
            )
        elif jwt:
            if not jwt.encoded:
                raise ValueError('JWT does not contain an encoded token')
            self.headers['Authorization'] = f'Bearer {jwt.encoded}'

        if app:
            if not config.debug:
                raise ValueError(
                    'Can not use FastAPI app for HTTP calls in non-debug mode'
                )
            self.session = AsyncHttpClient(
                app=app, cert=self.cert, verify=self.ca_filepath
            )
            return

        if self.pool in config.client_pools:
            self.session: HttpSession = config.client_pools[self.pool].session
            return

        self.create_session()

    def create_session(self) -> None:
        '''
        Creates a new HTTP session, replacing any session that may already
        be in the pool
        '''

        if self.pool in config.client_pools:
            config.client_pools.pop(self.pool, None)
            _LOGGER.debug(
                f'Removed HTTPX Session of pool {self.pool} '
                f'for connection to {self.host}'
            )

        _LOGGER.debug(
            f'Creating HTTPX Session in pool {self.pool} to {self.host}'
        )

        self.session: AsyncHttpClient = AsyncHttpClient(
            timeout=self.timeout,verify=self.ca_filepath, cert=self.cert,
            http2=True
        )

        config.client_pools[self.pool] = HttpSession(
            session=self.session, last_used=datetime.now(tz=timezone.utc)
        )

    @staticmethod
    async def call(api: str, method: str | HttpMethod = 'GET',
                   secret: Secret = None, jwt: JWT = None,
                   params: dict = None, data: dict = None,
                   headers: dict[str, str] = None, service_id: int = None,
                   member_id: UUID = None, files: list[tuple] = None,
                   account_id: UUID = None, network_name: str = None,
                   port: int = None, timeout: int = 10,
                   raise_for_error: bool = True, app: FastAPI = None
                   ) -> HttpResponse:

        '''
        Calls an API using the right credentials and accepted CAs

        Either the secret must be the secret of the pod (or test case) or
        the headers need to include an Authentication header with a valid JWT

        :param api: URL of the API to call. This can contain python placeholders,
        which will be replaced by network_name, service_id, member_id, and/or
        account_id
        :param method: HTTP method to use
        :param secret: secret to use for client M-TLS, must be None if JWT
        is provided
        :param jwt: JWT to use for authentication, must be None if the
        secret is provided
        :param jwt: JWT to use for authentication
        :param params: HTTP query parameters to use
        :param data: data to use for the JSON body of the HTTP request
        :param headers: HTTP headers to use
        :param service_id: service_id to use for M-TLS authentication
        :param member_id: member_id to use for M-TLS authentication
        :param account_id: account_id to use for M-TLS authentication
        :param network_name: name of the network to use for the HTTP call
        :param timeout: timeout for the HTTP call
        :param port: port to use for the HTTP call
        :param raise_for_error: throws an exception if HTTP response
        code >= 400
        :param app: FastAPI app to use for the HTTP call, only to be used
        for test cases
        :returns: HttpResonse
        :raises: ValueError, ByodaRuntimeError
        '''

        server: Server = config.server

        # This is used by the bootstrap of the pod, when the global variable is not yet
        # set
        if not network_name:
            network: Network = server.network
            network_name: str = network.name

        if isinstance(method, HttpMethod):
            method: str = method.value.upper()

        if not data:
            processed_data: bytes | str | None = None
        elif type(data) not in [str, bytes]:
            # orjson can serialize datetimes, UUIDs so we serialize
            # ourselves instead of having the HTTP client library do it
            processed_data = orjson.dumps(data)
        else:
            processed_data = data

        api = Paths.resolve(
            api, network_name, service_id=service_id, member_id=member_id,
            account_id=account_id
        )
        if method.upper() == 'GET':
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
            timeout=timeout, port=port, app=app
        )

        # Start with the headers that may have opentelemetry span id header
        updated_headers: dict[str, str] = deepcopy(client.headers)
        if headers:
            updated_headers |= headers

        # Don't set the content-type when we are uploading files
        if 'Content-Type' not in updated_headers and not files:
            updated_headers['Content-Type'] = 'application/json'

        retries: int = 0
        delay: float = 0.0
        while retries < ApiClient.MAX_RETRIES:
            skip_sleep: bool = False
            try:
                resp: HttpResponse = await client.session.request(
                    method, api, params=params, content=processed_data,
                    headers=updated_headers, files=files
                )
                break
            except (RequestError, TransportError, SSLCertVerificationError
                    ) as exc:
                raise ByodaRuntimeError(f'Error connecting to {api}: {exc}')
            except RuntimeError as exc:
                _LOGGER.debug(f'RuntimeError in call to API {api}: {exc}')
                client.create_session()
                if retries == 0:
                    skip_sleep = True


            # Exponential back-off with random jitter
            delay = ApiClient.RETRY_DELAYS[retries] + (random() * (delay or 0.2))

            if retries < len(ApiClient.RETRY_DELAYS) - 1:
                retries += 1

            _LOGGER.debug(
                f'Failed try #{retries} to call API, '
                f'waiting for {delay} seconds before retrying'
            )

            if not skip_sleep:
                await asyncio.sleep(delay)

        if retries >= ApiClient.MAX_RETRIES:
            raise ByodaRuntimeError(f'Error connecting to {api}: {exc}')

        if resp.status_code >= 400 and raise_for_error:
            if resp.status_code == 422:
                # This is the error returned by pydantic when the input
                # data does not match the model for the request
                data = resp.json()
                raise ByodaRuntimeError(
                    f'Incorrect input data to API {api}: {data["detail"]}'
                )
            raise ByodaRuntimeError(
                f'Failure to call API {api}: {resp.status_code}'
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
                          timeout: int, app: FastAPI | None = None
                          ) -> SyncHttpClient:
        '''
        Returns a HTTP client for calling APIs synchronously

        :param api: URL of the API to call.
        :param secret: secret to use as client for M-TLS authentication
        :param service_id: service_id to select which pool of persistent
        HTTPS connections to use
        :param timeout: timeout for the HTTP call
        :param app: FastAPI app to use for the HTTP call, only to be used
        for test cases
        :returns: HTTP client
        :raises: ValueError
        '''

        server: Server = config.server
        storage: FileStorage | None = None

        if hasattr(server, 'local_storage'):
            storage = server.local_storage

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

        if app:
            if not config.debug:
                raise ValueError(
                    'Can not use FastAPI app for HTTP calls in non-debug mode'
                )
            return SyncHttpClient(app=app, base_url=api)

        if pool in config.sync_client_pools:
            client: SyncHttpClient = config.sync_client_pools[pool]
            return client

        network: Network = server.network
        ca_filepath: str | None = None
        if not (api.startswith('https://dir')
                or api.startswith('https://proxy')):
            ca_filepath = storage.local_path + network.root_ca.cert_file

            _LOGGER.debug(f'Set server cert validation to {ca_filepath}')

        cert: tuple[str, str] | None = None
        if secret:
            if not storage:
                # Hack: podserver and svcserver use different attributes
                storage = server.storage_driver

            cert_filepath: str = storage.local_path + secret.cert_file
            key_filepath: str = secret.get_tmp_private_key_filepath()

            _LOGGER.debug(
                f'Setting client cert/key to {cert_filepath}, {key_filepath}'
            )
            cert = (cert_filepath, key_filepath)

        client = SyncHttpClient(
            timeout=timeout, verify=ca_filepath,cert=cert, http2=True
        )
        config.sync_client_pools[pool] = client

        return client

    @staticmethod
    def call_sync(api: str, method: str | HttpMethod = 'GET',
                  secret: Secret | None = None, params: dict | None = None,
                  data: dict | None = None, headers: dict | None = None,
                  service_id: int | None = None, member_id: UUID | None = None,
                  account_id: UUID | None = None, network_name: str | None = None,
                  port: int = 443, timeout: int = 10, app: FastAPI | None = None
                  ) -> HttpResponse:
        '''
        Calls an API using the right credentials and accepted CAs

        Either the secret must be the secret of the pod (or test case) or
        the headers need to include an Authentication header with a valid JWT

        :param api: URL of the API to call. This can contain python placeholders,
        which will be replaced by network_name, service_id, member_id, and/or
        account_id
        :param method: HTTP method to use
        :param secret: secret to use as client for M-TLS authentication
        :param params: HTTP query parameters to use
        :param data: data to use for the JSON body of the HTTP request
        :param headers: HTTP headers to use
        :param service_id: service_id to use for M-TLS authentication
        :param member_id: member_id to use for M-TLS authentication
        :param account_id: account_id to use for M-TLS authentication
        :param network_name: name of the network to use for the HTTP call
        :param timeout: timeout for the HTTP call
        :param port: port to use for the HTTP call
        :param app: FastAPI app to use for the HTTP call, only to be used
        for test cases
        :returns: (none)
        :raises: ValueError is service_id is specified for a secret that
        is not a MemberSecret
        '''
        server: Server = config.server

        client: SyncHttpClient = ApiClient._get_sync_client(
            api, secret, service_id, timeout, app=app
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
            headers=updated_headers
        )

        return resp
