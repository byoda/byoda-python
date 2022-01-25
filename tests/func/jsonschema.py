#!/usr/bin/env python3

'''
Test cases for json schema

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import json
import time
import unittest
import logging
import shutil
from uuid import uuid4

import fastjsonschema

from starlette.applications import Starlette

from multiprocessing import Process
import uvicorn

from python_graphql_client import GraphqlClient

from strawberry.asgi import GraphQL

from byoda.datastore.document_store import DocumentStoreType
from byoda.datatypes import CloudType

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.memberdata import MemberData
from byoda.datamodel.service import Service

from byoda.secrets import MemberSecret, MemberDataSecret

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from byoda import config

_LOGGER = logging.getLogger(__name__)

NETWORK = 'byodatest.net'
MEMBER_ID = 'aaaaaaaa-a9ac-4ea3-913c-d94981329d8f'
CONFIG_FILE = 'tests/collateral/config.yml'
DEFAULT_SCHEMA = 'services/addressbook.json'
TEST_DIR = '/tmp/byoda-tests/jsonschema'
BASE_URL = 'http://localhost:8000/graphql'
SERVICE_ID = 12345678

data = {
    'given_name': 'Steven',
    'family_name': 'Hessing',
}


class TestJsonSchema(unittest.TestCase):
    PROCESS = None
    APP_CONFIG = None

    @classmethod
    def setUpClass(cls):
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)
        shutil.copyfile(
            DEFAULT_SCHEMA, TEST_DIR + '/' + os.path.split(DEFAULT_SCHEMA)[-1]
        )
        network = Network.create(NETWORK, TEST_DIR, 'byoda')

        # Remaining environment variables used:
        config.server = PodServer(network)
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType.LOCAL,
            bucket_prefix='byodatest',
            root_dir=TEST_DIR
        )

        server.paths = network.paths

        account_id = uuid4()
        pod_account = Account(
            account_id, network, bootstrap=True
        )
        server.account = pod_account

        # We can't join the service as it doesn't exist in the network
        # so we have to use our own membership logic
        service = Service(
            network,
            service_id=SERVICE_ID,
            storage_driver=network.paths.storage_driver
        )
        service.name = 'jsonschema_test'
        service.create_secrets(network.services_ca)

        member = Member(SERVICE_ID, pod_account)
        member.member_id = MEMBER_ID
        pod_account.memberships[SERVICE_ID] = member

        member.tls_secret = MemberSecret(
            member.member_id, member.service_id, member.account
        )
        member.data_secret = MemberDataSecret(
            member.member_id, member.service_id, member.account
        )

        member.create_secrets(members_ca=service.members_ca)

        member.data_secret.create_shared_key()

        member.schema = member.load_schema(
            os.path.split(DEFAULT_SCHEMA)[-1],
            verify_signatures=False
        )

        member.data = MemberData(
            member, member.paths, member.document_store
        )
        member.data.save_protected_shared_key()
        member.data.initalize()
        member.data.save()

        app = Starlette(debug=True)
        graphql_app = GraphQL(member.schema.gql_schema, debug=True)
        for path in ['/', '/graphql']:
            app.add_route(path, graphql_app)

        cls.PROCESS = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={
                'host': '0.0.0.0',
                'port': server.HTTP_PORT,
                'log_level': 'info'
            },
            daemon=True
        )
        cls.PROCESS.start()
        time.sleep(3)

    @classmethod
    def tearDownClass(cls):
        cls.PROCESS.terminate()

    def test_jsonschema(self):
        with open(DEFAULT_SCHEMA) as fd:
            fastjson_schema = json.load(fd)

        validate = fastjsonschema.compile(fastjson_schema)

        test = validate(data)
        self.assertEqual(data, test)

        # obj = MemberData(
        #    schema, storage_driver
        # )
        # obj._load_from_file('tests/collateral/memberdata.json')

        member_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={MEMBER_ID}.members-{SERVICE_ID}.{NETWORK}',
            'X-Client-SSL-Issuing-CA': f'CN=members-ca.{NETWORK}'
        }

        client = GraphqlClient(endpoint=BASE_URL)

        query = '''
            query {
                member {
                    joined
                    member_id
                }
            }
        '''
        result = client.execute(query=query, headers=member_headers)
        self.assertEqual(result['data']['member']['member_id'], str(MEMBER_ID))

        query = '''
            mutation {
                mutate_person(
                    given_name: "Peter",
                    additional_names: "",
                    family_name: "Hessing",
                    email: "steven@byoda.org",
                    homepage_url: "https://some.place/",
                    avatar_url: "https://some.place/avatar"
                ) {
                    given_name
                    additional_names
                    family_name
                    email
                    homepage_url
                    avatar_url
                }
            }
        '''
        result = client.execute(query=query, headers=member_headers)

        query = '''
            query {
                person {
                    given_name
                    additional_names
                    family_name
                    email
                    homepage_url
                    avatar_url
                }
            }
        '''
        result = client.execute(query=query, headers=member_headers)
        self.assertEqual(result['data']['person']['given_name'], 'Peter')

        query = '''
            query {
                memberlogs {
                    timestamp
                    remote_addr
                    action
                    message
                }
            }
        '''
        result = client.execute(query=query, headers=member_headers)
        self.assertEqual(result['data']['memberlogs'], [])

        query = '''
            mutation {
                append_memberlogs (
                    timestamp: "2022-01-21T04:01:36.798843+00:00",
                    remote_addr: "10.0.0.1",
                    action: "join",
                    message: "blah"
                ) {
                    timestamp
                    remote_addr
                    action
                    message
                }
            }
        '''
        result = client.execute(query=query, headers=member_headers)
        # self.assertEqual(result['data']['memberlogs'], None)
        self.assertEqual(
            result['data']['append_memberlogs']['remote_addr'], '10.0.0.1'
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
