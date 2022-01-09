#!/usr/bin/env python3

'''
Test cases for signatures for a service contract

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import json
import shutil
import unittest
import logging

from byoda import config

from byoda.util.logger import Logger

from byoda.datamodel.memberdata import MemberData, Schema

from byoda.servers import PodServer

from byoda.storage import FileStorage


_LOGGER = logging.getLogger(__name__)

SCHEMA = 'tests/collateral/service-contract.json'

TEST_DIR = '/tmp/byoda-tests/pod-schema-signature'


class TestAccountManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        config.server = PodServer()
        config.server.network = network


    @classmethod
    def tearDownClass(cls):
        cls.PROCESS.terminate()

    def test_network_account_put(self):
        API = BASE_URL + '/v1/network/account'

        uuid = uuid4()

        network_name = TestDirectoryApis.APP_CONFIG['application']['network']

        # PUT, with auth
        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={uuid}.accounts.{network_name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network_name}'
        }
        response = requests.put(API, headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ipv4_address'], '127.0.0.1')
        self.assertEqual(data['ipv6_address'], None)

    def test_network_account_post(self):