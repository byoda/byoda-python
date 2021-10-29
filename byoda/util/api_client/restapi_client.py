'''
RestApiClient, derived from ApiClient for calling REST APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging
from enum import Enum
from typing import Dict
from uuid import UUID

import requests


from byoda.secrets import Secret

from .api_client import ApiClient


_LOGGER = logging.getLogger(__name__)


class HttpMethod(Enum):
    # flake8: noqa=E221
    GET         = 'get'
    POST        = 'post'
    PUT         = 'put'
    PATCH       = 'patch'
    DELETE      = 'delete'
    HEAD        = 'head'

class RestApiClient:
    '''

    '''

    def __init__(self):
        pass

    @staticmethod
    def call(api: str, method: HttpMethod = HttpMethod.GET, secret: Secret = None,
             params: Dict = None, data: Dict = None, service_id: int = None,
             member_id: UUID = None, account_id: UUID = None) -> requests.Response:

        '''
        Calls an API using the right credentials and accepted CAs
        '''

        if method == HttpMethod.POST:
            if (service_id is not None or member_id is not None
                or account_id is not None):
                raise ValueError(
                    'BYODA POST APIs do not accept query parameters'
                )
            paths = api.split('/')
            try:
                _LOGGER.debug('Removing identifier from end of request for POST call')
                int(paths[-1])
                shortend_api = '/'.join(paths[0:-1])
                _LOGGER.debug(f'Modified POST API call from {api} to {shortend_api}')
                api = shortend_api
            except:
                # API URL did not end with an ID specifier
                pass

        response = ApiClient.call(
            api, method.value, secret=secret, params=params, data=data, service_id=service_id,
            member_id=member_id, account_id=account_id
        )

        return response
