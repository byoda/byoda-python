'''
GraphQlClient, for performing GraphQL queries, either using HTTP or websockets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging


from byoda.secrets.secret import Secret

from byoda.util.api_client.restapi_client import HttpMethod

from .api_client import ApiClient
from .api_client import HttpResponse


_LOGGER = logging.getLogger(__name__)


class GraphQlClient:
    def __init__(self):
        pass

    @staticmethod
    async def call(url: str, query: bytes, secret: Secret = None,
                   headers: dict = None, vars: dict = None,
                   timeout: int = 10):

        body = GraphQlClient.prep_query(query, vars)

        resp = await ApiClient.call(
            url, HttpMethod.POST, secret=secret, data=body, headers=headers,
            timeout=timeout
        )

        return resp

    @staticmethod
    async def close_all():
        await ApiClient.close_all()

    @staticmethod
    def call_sync(url: str, query: bytes,
                  vars: dict = None, headers: dict = None,
                  secret: Secret = None, timeout: int = 10
                  ) -> HttpResponse:

        body = GraphQlClient.prep_query(query, vars)

        resp = ApiClient.call_sync(
            url, HttpMethod.POST, data=body, headers=headers,
            secret=secret, timeout=timeout
        )

        return resp

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
