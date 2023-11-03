'''
DataApiClient, derived from ApiClient for calling REST Data APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

from copy import copy
from uuid import UUID
from uuid import uuid4

from logging import getLogger

from fastapi import FastAPI

from byoda.requestauth.jwt import JWT

from byoda.util.api_client.api_client import HttpResponse

from byoda.datatypes import DataRequestType
from byoda.datatypes import DataFilterType
from byoda.datatypes import DATA_API_URL
from byoda.datatypes import DATA_API_PROXY_URL

from byoda.secrets.secret import Secret
from byoda.secrets.member_secret import MemberSecret

from byoda.util.logger import Logger

from byoda import config

from .api_client import ApiClient, HttpMethod


_LOGGER: Logger = getLogger(__name__)


class DataApiClient:
    # We can't use PodServer.HTTP_PORT here because of circular import
    INTERNAL_HTTP_PORT: int = 8000

    SUPPORTED_REQUEST_TYPES: list[DataRequestType] = [
        DataRequestType.QUERY, DataRequestType.APPEND, DataRequestType.UPDATE,
        DataRequestType.MUTATE, DataRequestType.DELETE
    ]

    '''
    '''
    def __init__(self):
        pass

    @staticmethod
    async def call(service_id: int, class_name: str, action: DataRequestType,
                   secret: Secret = None, jwt: JWT = None,
                   use_proxy: bool = False,
                   custom_domain: str | None = None,
                   network: str = 'byoda.net',
                   headers: dict[str, str] | None = None,
                   params: dict | None = None,
                   data: dict | None = None,
                   member_id: UUID | None = None,
                   remote_member_id: UUID | None = None,
                   query_id: UUID | None = None,
                   first: int = None, after: str = None,
                   fields: set[str] = None,
                   depth: int = None, relations: list[str] = None,
                   data_filter: DataFilterType | None = None,
                   timeout: int | float = 1,
                   internal: bool = False, app: FastAPI = None
                   ) -> HttpResponse:

        '''
        Calls an API using the right credentials and accepted CAs

        :param service_id: ID of service to call the API from
        :param class_name: name of class to call the API for
        :param action: the type of action to request
        :param secret: secret to use for client M-TLS, must be None if JWT
        is provided
        :param jwt: JWT to use for authentication
        :param use_proxy: call API via proxy
        :param custom_domain: custom domain to use for the API call
        :param jwt: JWT to use for authentication, must be None if the
        secret is provided
        :param params: HTTP query parameters
        :param data: data to send in the body of the request
        :param member_id: the member_id of the pod you want to call, required
        if use_proxy is set to True
        :param remote_member_id: the member ID of the pod that you want the
        pod that handles our request to proxy our request to
        :param headers: a list of HTTP headers to add to the request
        :param timeout: timeout in seconds
        :param internal: whether to use the internal API or not, also used
        :param app: FastAPI app to use for the request, used for test cases
        for test cases
        :returns: HttpResponse
        :raises: ValueError
        '''

        if action not in DataApiClient.SUPPORTED_REQUEST_TYPES:
            raise ValueError(f'Unsupported action: {action.value}')

        data_url: str
        port: int
        data_url, port = DataApiClient.get_url(
            service_id, class_name, action, headers, use_proxy, custom_domain,
            network, jwt, member_id, internal, app
        )

        _LOGGER.debug(f'Using data URL {data_url}')
        api_data: dict[str, object] = copy(data) if data else {}
        if first:
            api_data['first'] = first
        if after:
            api_data['after'] = after
        if fields:
            api_data['fields'] = fields
        if data_filter:
            api_data['filter'] = data_filter
        if depth:
            api_data['depth'] = depth
        if relations:
            api_data['relations'] = relations
        if remote_member_id:
            api_data['remote_member_id'] = remote_member_id

        if query_id:
            api_data['query_id'] = query_id
        elif 'query_id' not in api_data:
            api_data['query_id'] = uuid4()

        if depth:
            timeout *= depth

        resp: HttpResponse = await ApiClient.call(
            data_url, HttpMethod.POST, secret=secret, jwt=jwt,
            params=params, data=api_data, headers=headers,
            service_id=service_id, member_id=member_id, network_name=network,
            port=port, timeout=timeout, app=app
        )

        return resp

    @staticmethod
    def get_url(service_id: int, class_name: str,
                action: DataRequestType | str,
                headers: dict[str, str],
                use_proxy: bool, custom_domain: str,
                network: str, jwt: JWT, member_id: UUID,
                internal: bool, app: FastAPI | None = None) -> (str, int):
        '''
        Figures out the URL to use for the call
        Use cases:
        - test cases with internal & app set to port 8000,
        - test cases that call_data_api using custom domain to port 444
        - call_data_api using custom domain to port 443
        - call_data_api via proxy to port 443
        - pod calls port 444 without use_proxy or custom_domain

        :param service_id: ID of service to call the API from
        :param class_name: name of class to call the API for
        :param action: the type of action to request
        :param secret: secret to use for client M-TLS, must be None if JWT
        is provided
        :param jwt: JWT to use for authentication
        :param use_proxy: call API via proxy
        :param custom_domain: custom domain to use for the API call
        :param network: the domain for the Byoda network
        :param jwt: JWT to use for authentication, must be None if the
        secret is provided
        :param params: HTTP query parameters
        :param data: data to send in the body of the request
        :param member_id: the member_id of the pod you want to call, required
        if not performing an internal API call
        :param headers: a list of HTTP headers to add to the request
        :param timeout: timeout in seconds
        :param internal: whether to use the internal API or not, also used
        :param app: FastAPI app to use for the request, used for test cases
        for test cases
        :returns: tuple of url to call and port to connect to
        :raises: ValueError
        '''

        if app and not config.debug:
            raise ValueError('Not running test cases')

        if not (app or internal):
            if use_proxy and not (member_id and network):
                raise ValueError(
                    'Member ID and network must be provided when using proxy'
                )

        if custom_domain and use_proxy:
            raise ValueError(
                'Cannot use custom domain and proxy at the same time'
            )

        if isinstance(action, str):
            action = DataRequestType(action)

        api_template: str = DATA_API_URL
        protocol: str = 'https'
        port: int = 443

        if internal or app:
            if not app:
                _LOGGER.debug('Calling Data API via internal port')
            else:
                _LOGGER.debug('Calling Data API via test case')

            port = DataApiClient.INTERNAL_HTTP_PORT
            protocol = 'http'

            data_url = api_template.format(
                protocol=protocol, fqdn='127.0.0.1', port=port,
                service_id=service_id, class_name=class_name,
                action=action.value
            )
        elif custom_domain:
            _LOGGER.debug(f'Using custom_domain {custom_domain}')
            data_url = api_template.format(
                protocol=protocol, fqdn=custom_domain, port=port,
                service_id=service_id, class_name=class_name,
                action=action.value
            )
        elif use_proxy:
            _LOGGER.debug(f'Using proxy for member: {member_id}')
            if not member_id:
                raise ValueError('Member ID must be provided when using proxy')

            data_url = DATA_API_PROXY_URL.format(
                protocol=protocol, network=network,
                service_id=service_id, member_id=member_id,
                class_name=class_name, action=action.value,
            )
        else:
            host: str = MemberSecret.create_commonname(
                member_id, service_id, network
            )

            port = 444
            if headers and 'Authorization' in headers:
                # This must be a test case calling a pod with a JWT
                port = 443

            _LOGGER.debug(
                f'Calling Data API of pod {host} with port {port}')

            data_url: str = api_template.format(
                protocol=protocol, fqdn=host, port=port,
                service_id=service_id, class_name=class_name,
                action=action.value
            )

        return data_url, port

    @staticmethod
    async def close_all():
        await ApiClient.close_all()

    @staticmethod
    def call_sync(api: str, method: HttpMethod = HttpMethod.GET,
                  secret: Secret = None, params: dict = None,
                  data: dict = None, service_id: int = None,
                  member_id: UUID = None, account_id: UUID = None
                  ) -> HttpResponse:

        '''
        Calls an API using the right credentials and accepted CAs

        :param api: URL of API to call
        :param method: GET, POST, etc.
        :param secret: secret to use for client M-TLS
        :param params: HTTP query parameters
        :param data: data to send in the body of the request
        :param service_id:
        :param member_id:
        :param account_id:
        '''

        if method == HttpMethod.POST:
            if member_id is not None or account_id is not None:
                raise ValueError(
                    'BYODA POST APIs do not accept query parameters for '
                    'member_id and account_id'
                )
            try:
                _LOGGER.debug(
                    'Removing identifier from end of request for POST call'
                )
                paths = api.split('/')
                int(paths[-1])
                shortend_api = '/'.join(paths[0:-1])
                _LOGGER.debug(
                    f'Modified POST API call from {api} to {shortend_api}'
                )
                api = shortend_api
            except (KeyError, ValueError):
                # API URL did not end with an ID specifier
                pass

        resp: HttpResponse = ApiClient.call_sync(
            api, method.value, secret=secret, params=params, data=data,
            service_id=service_id, member_id=member_id, account_id=account_id,
        )

        return resp
