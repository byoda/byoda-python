#!/usr/bin/env python3

'''
Test the GraphQL API

As these test cases are directly run against the GraphQL APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license
'''

import sys

import unittest

from gql import Client
from gql import gql
from gql.transport.aiohttp import AIOHTTPTransport
from aiohttp import ClientTimeout

from byoda.util.logger import Logger

NETWORK = 'byoda.net'
BASE_URL = 'http://localhost:8001/api'

TRANSPORT = AIOHTTPTransport(
    url=BASE_URL + '/v1/member/data',
    timeout=60
)


# (given_name: "Blah", family_name: "Gaap", email: "blah@gaap.com")
class TestGraphQL(unittest.TestCase):
    def test_member_get(self):
        # Create a GraphQL client using the defined transport
        client = Client(
            transport=TRANSPORT, fetch_schema_from_transport=True
        )
        query = gql(
            '''
                query {
                    person(given_name: "Steven") {
                        given_name
                        family_name
                        email
                    }
                }
            '''
        )
        result = client.execute(query)
        print(result)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
