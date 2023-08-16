'''
RestApiClient, derived from ApiClient for calling REST APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


import logging
from uuid import UUID

import requests
import aiohttp


from byoda.secrets.secret import Secret

from .api_client import ApiClient, HttpMethod


_LOGGER = logging.getLogger(__name__)


class RestApiClient:
    '''
    '''

    def __init__(self):
        pass

    @staticmethod
    async def call(api: str, method: HttpMethod = HttpMethod.GET,
                   secret: Secret = None, params: dict = None,
                   data: dict = None, service_id: int = None,
                   member_id: UUID = None, account_id: UUID = None,
                   headers: dict[str, str] = None
                   ) -> aiohttp.ClientResponse:

        '''
        Calls an API using the right credentials and accepted CAs

        :param api: URL of API to call
        :param method: GET, POST, etc.
        :param secret: secret to use for client M-TLS
        :param params: HTTP query parameters
        :param data: data to send in both of the request
        :param service_id:
        :param member_id:
        :param account_id:
        :param headers: a list of HTTP headers to add to the request
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

        response: aiohttp.ClientResponse = await ApiClient.call(
            api, method, secret=secret, params=params, data=data,
            headers=headers, service_id=service_id, member_id=member_id,
            account_id=account_id,
        )

        return response

    @staticmethod
    async def close_all():
        await ApiClient.close_all()

    @staticmethod
    def call_sync(api: str, method: HttpMethod = HttpMethod.GET,
                  secret: Secret = None, params: dict = None,
                  data: dict = None, service_id: int = None,
                  member_id: UUID = None, account_id: UUID = None
                  ) -> requests.Response:

        '''
        Calls an API using the right credentials and accepted CAs

        :param api: URL of API to call
        :param method: GET, POST, etc.
        :param secret: secret to use for client M-TLS
        :param params: HTTP query parameters
        :param data: data to send in both of the request
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

        response: requests.Response = ApiClient.call_sync(
            api, method.value, secret=secret, params=params, data=data,
            service_id=service_id, member_id=member_id, account_id=account_id,
        )

        return response
