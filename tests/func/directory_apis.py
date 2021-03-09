#!/usr/bin/env python3

'''
Test the Directory APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

'''

import sys

from uuid import uuid4, UUID
from ipaddress import ip_address
import unittest
import requests

from byoda.util import Logger


NETWORK = 'byoda.net'
BASE_URL = 'http://localhost:5000/api'


class TestDirectoryApis(unittest.TestCase):
    def test_network_account(self):

        API = BASE_URL + '/v1/network/account/'
        # GET
        response = requests.get(API)
        data = response.json()
        print(data)
        self.assertEqual(data['accounts'], 1)
        self.assertEqual(data['remote_addr'], '127.0.0.1')
        uuid = UUID(data['uuid'])


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
