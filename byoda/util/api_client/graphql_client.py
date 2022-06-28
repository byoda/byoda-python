'''
GraphQlClient, for performing GraphQL queries

Based on https://github.com/prodigyeducation/python-graphql-client/blob/master/python_graphql_client/

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import Dict
from uuid import UUID

import aiohttp


from byoda.secrets import Secret
from byoda.util.api_client.restapi_client import HttpMethod

from .api_client import ApiClient


_LOGGER = logging.getLogger(__name__)


class GraphQlClient:
    def __init__(self):
        pass

    @staticmethod
    async def call(url: str, query: bytes, secret: Secret,
                   variables: Dict = None) -> aiohttp.ClientResponse:

        if isinstance(query, bytes):
            query = query.decode('utf-8')

        body = {"query": query}

        if variables:
            body["variables"] = variables

        response: aiohttp.ClientResponse = await ApiClient.call(
            url, HttpMethod.POST, secret=secret, data=body
        )

        return response

