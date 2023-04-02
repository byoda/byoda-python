'''
GraphQlClient, for performing GraphQL queries, either using HTTP or websockets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import orjson
import logging

import aiohttp
import requests
import websockets

from gql import gql

from byoda.secrets import Secret
from byoda.util.api_client.restapi_client import HttpMethod

from .api_client import ApiClient


_LOGGER = logging.getLogger(__name__)


class GraphQlClient:
    def __init__(self):
        pass

    @staticmethod
    async def call(url: str, query: bytes, secret: Secret = None,
                   headers: dict = None, vars: dict = None,
                   timeout: int = 10) -> aiohttp.ClientResponse:

        body = GraphQlClient.prep_query(query, vars)

        response: aiohttp.ClientResponse = await ApiClient.call(
            url, HttpMethod.POST, secret=secret, data=body, headers=headers,
            timeout=timeout
        )

        return response

    @staticmethod
    def call_sync(url: str, query: bytes,
                  vars: dict = None, headers: dict = None,
                  secret: Secret = None, timeout: int = 10
                  ) -> requests.Response:

        body = GraphQlClient.prep_query(query, vars)

        response = ApiClient.call_sync(
            url, HttpMethod.POST, data=body, headers=headers,
            secret=secret, timeout=timeout
        )

        return response

    @staticmethod
    def prep_query(query: str, vars: dict) -> str:
        '''
        Generates the GraphQL query to be used in a HTTP POST call
        '''

        if isinstance(query, bytes):
            query = query.decode('utf-8')

        body = {"query": query}

        if vars:
            body["variables"] = vars

        return body


class GraphQlWsClient(GraphQlClient):
    async def subscribe(self, url: str, query: bytes, secret: Secret = None,
                        headers: dict = None, vars: dict = None,
                        timeout: int = 10) -> aiohttp.ClientResponse:

        body = GraphQlWsClient.prep_query(query, vars)

        async with websockets.connect(url) as websocket:
            pass

        return

    @staticmethod
    def prep_query(query: str, vars: dict) -> str:
        '''
        Generates the GraphQL query to be used in a HTTP POST call
        '''

        if isinstance(query, bytes):
            query = query.decode('utf-8')

        body = {
            'operationName': 'subscription',
            'query': query
        }

        if vars:
            body['variables'] = vars

        request_message = orjson.dumps(
            {
                'type': 'start',
                'id': '1',
                'payload': body
            }

        )
        return body