#!/usr/bin/env python3

'''
Test the Directory APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license
'''

import os
import sys
import unittest
import requests
import shutil
import time
from uuid import uuid4, UUID

from multiprocessing import Process
import uvicorn

from python_graphql_client import GraphqlClient

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
from podserver.routers import member

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

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
        pod_account.join(BYODA_PRIVATE_SERVICE, 1)

        app = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', None, [account, member]
        )

        for account_member in pod_account.memberships.values():
            account_member.enable_graphql_api(app)
            account_member.update_registration()

        cls.PROCESS = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={
                'host': '0.0.0.0',
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

    def test_pod_rest_api(self):
        account = config.server.account
        account_id = account.account_id
        network = account.network

        service_id = 0

        account_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={account_id}.accounts.{network.name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.name}'
        }

        API = BASE_URL + '/v1/pod/account'
        response = requests.get(API, headers=account_headers)
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
        self.assertEqual(len(data['services']), 0)

        API = BASE_URL + '/v1/pod/member'
        response = requests.get(
            API + f'/service_id/{service_id}', headers=account_headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['account_id'], account_id)
        self.assertEqual(data['network'], 'byoda.net')
        self.assertTrue(isinstance(data['member_id'], str))
        member_id = UUID(data['member_id'])
        self.assertEqual(data['service_id'], service_id)
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['name'], 'private')
        self.assertEqual(data['owner'], 'Steven Hessing')
        self.assertEqual(data['website'], 'https://www.byoda.org/')
        self.assertEqual(data['supportemail'], 'steven@byoda.org')
        self.assertEqual(
            data['description'], (
                'the private service for which no data will be shared with '
                'services or their members'
            )
        )
        self.assertGreater(len(data['certificate']), 80)
        self.assertGreater(len(data['private_key']), 80)

        member_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={member_id}.members-0.{NETWORK}',
            'X-Client-SSL-Issuing-CA': f'CN=members-ca.{NETWORK}'
        }

        url = BASE_URL + f'/v1/data/service-{service_id}'
        client = GraphqlClient(endpoint=url)

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
        result = client.execute(query=query, headers=member_headers)
        self.assertEqual(
            result['data']['mutatePerson']['givenName'], 'Peter'
        )
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
        result = client.execute(query=query, headers=member_headers)

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

        result = client.execute(query=query, headers=member_headers)
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
        result = client.execute(query, headers=member_headers)
        self.assertEqual(
            result['data']['mutateMember']['memberId'], '0'
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
