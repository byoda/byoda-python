'''
GraphQlClient, for performing GraphQL queries

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import Dict

import aiohttp
import requests

from byoda.secrets import Secret
from byoda.util.api_client.restapi_client import HttpMethod

from .api_client import ApiClient


_LOGGER = logging.getLogger(__name__)


class GraphQlClient:
    def __init__(self):
        pass

    @staticmethod
    async def call(url: str, query: bytes, secret: Secret = None,
                   headers: Dict = None, vars: Dict = None,
                   timeout: int = 10) -> aiohttp.ClientResponse:

        body = GraphQlClient.prep_query(query, vars)

        response: aiohttp.ClientResponse = await ApiClient.call(
            url, HttpMethod.POST, secret=secret, data=body, headers=headers,
            timeout=timeout
        )

        return response

    @staticmethod
    def call_sync(url: str, query: bytes,
                  vars: Dict = None, headers: Dict = None,
                  secret: Secret = None, timeout: int = 10
                  ) -> requests.Response:

        body = GraphQlClient.prep_query(query, vars)

        response = ApiClient.call_sync(
            url, HttpMethod.POST, data=body, headers=headers,
            secret=secret, timeout=timeout
        )

        return response

    @staticmethod
    def prep_query(query: str, vars: Dict) -> str:
        '''
        Generates the GraphQL query to be used in a HTTP POST call
        '''

        if isinstance(query, bytes):
            query = query.decode('utf-8')

        body = {"query": query}

        if vars:
            body["variables"] = vars

        return body
