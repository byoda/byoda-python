#!/usr/bin/env python3

'''
Test the GraphQL API

As these test cases are directly run against the GraphQL APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license
'''

import sys
import unittest

from python_graphql_client import GraphqlClient

from byoda.util.logger import Logger
from byoda.config import DEFAULT_NETWORK

NETWORK = DEFAULT_NETWORK
BASE_URL = 'http://localhost:8001/api'

uuid = '9cf09af6-ad55-4c2f-a552-9bde79ea9026'
service_id = 0

HEADERS = {
    'X-Client-SSL-Verify': 'SUCCESS',
    'X-Client-SSL-Subject': f'CN={uuid}.members-{service_id}.{NETWORK}',
    'X-Client-SSL-Issuing-CA': f'CN=members-ca.{NETWORK}'
}


class TestGraphQL(unittest.TestCase):
    def test_member_get(self):

        url = BASE_URL + '/v1/data/service-0'
        client = GraphqlClient(endpoint=url)
        query = '''
                query {
                    person {
                        givenName
                        additionalNames
                        familyName
                        email
                        homepageUrl
                        avatarUrl
                    }
                }
            '''
        result = client.execute(query=query, headers=HEADERS)
        # self.assertEqual(result['data']['person']['givenName'], 'Steven')

        query = '''
                mutation {
                    mutatePerson(
                        givenName: "Peter",
                        additionalNames: "",
                        familyName: "Hessing",
                        email: "steven@byoda.org",
                        homepageUrl: "https://some.place/",
                        avatarUrl: "https://some.place/avatar"
                    ) {
                        givenName
                        additionalNames
                        familyName
                        email
                        homepageUrl
                        avatarUrl
                    }
                }
            '''
        result = client.execute(query=query, headers=HEADERS)
        self.assertEqual(
            result['data']['mutatePerson']['givenName'], 'Peter'
        )

        query = '''
                mutation {
                    mutatePerson(
                        givenName: "Steven",
                        additionalNames: "",
                        familyName: "Hessing",
                        email: "steven@byoda.org",
                        homepageUrl: "https://some.place/",
                        avatarUrl: "https://some.place/avatar"
                    ) {
                        givenName
                        additionalNames
                        familyName
                        email
                        homepageUrl
                        avatarUrl
                    }
                }
            '''

        result = client.execute(query=query, headers=HEADERS)
        self.assertEqual(
            result['data']['mutatePerson']['givenName'], 'Steven'
        )
        query = '''
                mutation {
                    mutateMember(
                        memberId: "0",
                        joined: "2021-09-19T09:04:00+07:00"
                    ) {
                        memberId
                    }
                }
            '''
        result = client.execute(query, headers=HEADERS)
        self.assertEqual(
            result['data']['mutateMember']['memberId'], '0'
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
