'''
GraphQlClient, for performing GraphQL queries

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import Dict

import aiohttp


from byoda.secrets import Secret
from byoda.util.api_client.restapi_client import HttpMethod

from .api_client import ApiClient


_LOGGER = logging.getLogger(__name__)


class GraphQlClient:
    def __init__(self):
        pass

    @staticmethod
    async def call(url: str, query: bytes, secret: Secret = None,
                   headers: Dict = None, variables: Dict = None,
                   timeout: int = 10) -> aiohttp.ClientResponse:

        if isinstance(query, bytes):
            query = query.decode('utf-8')

        body = {"query": query}

        if variables:
            body["variables"] = variables

        response: aiohttp.ClientResponse = await ApiClient.call(
            url, HttpMethod.POST, secret=secret, data=body, headers=headers,
            timeout=timeout
        )

        return response
