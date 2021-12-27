#!/usr/bin/env python3

'''
Test the Directory APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license
'''

import sys
import os
import unittest
import requests
import shutil
import time
from uuid import uuid4

from multiprocessing import Process
import uvicorn

# from byoda.datamodel import Account
from byoda.datamodel import Network
from byoda.datamodel import Account

from byoda.datamodel.service import BYODA_PRIVATE_SERVICE


from byoda.servers import PodServer

from byoda.datastore import DocumentStoreType
from byoda.datatypes import CloudType

from byoda.util.logger import Logger
from byoda.util import setup_api

from byoda import config

from podserver.util import get_environment_vars
from podserver.routers import account

# Settings must match config.yml used by directory server
NETWORK = 'byoda.net'

TEST_DIR = '/tmp/byoda-tests/pod_apis'
BASE_URL = 'http://localhost:{PORT}/api'

_LOGGER = None


class TestDirectoryApis(unittest.TestCase):
    PROCESS = None
    APP_CONFIG = None

    @classmethod
    def setUpClass(cls):
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        os.environ['ROOT_DIR'] = TEST_DIR
        os.environ['BUCKET_PREFIX'] = 'byoda'
        os.environ['CLOUD'] = 'LOCAL'
        os.environ['NETWORK'] = 'byoda.net'
        os.environ['ACCOUNT_ID'] = str(uuid4())
        os.environ['ACCOUNT_SECRET'] = 'test'
        os.environ['LOGLEVEL'] = 'DEBUG'
        os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
        os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

        # Remaining environment variables used:
        network_data = get_environment_vars()

        config.server = PodServer()
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType(network_data['cloud']),
            bucket_prefix=network_data['bucket_prefix'],
            root_dir=network_data['root_dir']
        )

        network = Network(network_data, network_data)
        server.network = network
        server.paths = network.paths

        pod_account = Account(
            network_data['account_id'], network, bootstrap=True
        )
        server.account = pod_account

        pod_account.create_account_secret()
        pod_account.create_data_secret()
        pod_account.register()

        server.get_registered_services()
        server.join_service(BYODA_PRIVATE_SERVICE, network_data)

        app = setup_api(
            'Byoda test dirserver', 'server for testing directory APIs',
            'v0.0.1', None, [account]
        )
        cls.PROCESS = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={
                'host': '127.0.0.1',
                'port': server.HTTP_PORT,
                'log_level': 'debug'
            },
            daemon=True
        )
        cls.PROCESS.start()
        time.sleep(3)

    @classmethod
    def tearDownClass(cls):
        cls.PROCESS.terminate()

    def test_network_account_put(self):
        API = BASE_URL + '/v1/pod/account'

        account = config.server.account
        account_id = account.account_id
        network = account.network
        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={account_id}.accounts.{network.name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.name}'
        }
        response = requests.get(API, headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['account_id'], str(account_id))
        self.assertEqual(data['network'], NETWORK)
        self.assertTrue(data['started'].startswith('202'))
        self.assertEqual(data['cloud'], 'LOCAL')
        self.assertEqual(data['private_bucket'], 'LOCAL')
        self.assertEqual(data['public_bucket'], '/var/www/wwwroot/public')
        self.assertEqual(data['root_directory'], '/tmp/byoda-tests/pod_apis')
        self.assertEqual(data['loglevel'], 'DEBUG')
        self.assertEqual(data['private_key_secret'], 'byoda')
        self.assertEqual(data['bootstrap'], True)
        self.assertEqual(len(data['services']), 1)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
