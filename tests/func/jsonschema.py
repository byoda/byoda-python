#!/usr/bin/env python3

'''
Test cases for json schema

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import orjson
import asyncio
import unittest
import logging
import shutil
from uuid import uuid4, UUID

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
DEFAULT_SCHEMA = 'tests/collateral/addressbook.json'
TEST_DIR = '/tmp/byoda-tests/jsonschema'
BASE_URL = 'http://localhost:8000/graphql'
SERVICE_ID = 4294929430

data = {
    'given_name': 'Steven',
    'family_name': 'Hessing',
}

member_query = '''
    query {
        member {
            joined
            member_id
        }
    }
'''

person_query = '''
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

memberlogs_query = '''
    query {
        memberlogs {
            timestamp
            remote_addr
            action
            message
        }
    }
'''

network_links_query = '''
    query {
        network_links {
            timestamp
            member_id
            relation
        }
    }
'''

person_mutation = '''
    mutation (
            $given_name: String!,
            $additional_names: String!,
            $family_name: String!,
            $email: String!,
            $homepage_url: String!,
            $avatar_url: String!
    ) {
        mutate_person(
            given_name: $given_name,
            additional_names: $additional_names,
            family_name: $family_name,
            email: $email,
            homepage_url: $homepage_url,
            avatar_url: $avatar_url
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

memberlogs_mutation = '''
    mutation (
            $timestamp: String!,
            $remote_addr: String!,
            $action: String!,
            $message: String!
    ) {
        append_memberlogs (
            timestamp: $timestamp,
            remote_addr: $remote_addr,
            action: $action,
            message: $message
        ) {
            timestamp
            remote_addr
            action
            message
        }
    }
'''

network_links_mutation = '''
    mutation (
            $timestamp: String!,
            $member_id: String!,
            $relation: String!
    ) {
        append_network_links (
            timestamp: $timestamp,
            member_id: $member_id,
            relation: $relation
        ) {
            timestamp
            member_id
            relation
        }
    }
'''


class TestJsonSchema(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)
        shutil.copyfile(
            DEFAULT_SCHEMA, TEST_DIR + '/' + os.path.split(DEFAULT_SCHEMA)[-1]
        )
        network = await Network.create(NETWORK, TEST_DIR, 'byoda')

        # Remaining environment variables used:
        config.server = PodServer(network)
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType.LOCAL,
            bucket_prefix='byodatest',
            root_dir=TEST_DIR
        )

        server.paths = network.paths

        account_id = uuid4()
        pod_account = Account(account_id, network)
        await pod_account.paths.create_account_directory()
        await pod_account.load_memberships()

        server.account = pod_account

        # We can't join the service as it doesn't exist in the network
        # so we have to use our own membership logic
        service = Service(
            network=network,
            service_id=SERVICE_ID,
            storage_driver=network.paths.storage_driver
        )
        service.name = 'jsonschema_test'
        await service.create_secrets(network.services_ca)

        member = Member(SERVICE_ID, pod_account)
        await member.setup()

        member.member_id = UUID(MEMBER_ID)
        pod_account.memberships[SERVICE_ID] = member

        member.tls_secret = MemberSecret(
            member.member_id, member.service_id, member.account
        )
        member.data_secret = MemberDataSecret(
            member.member_id, member.service_id, member.account
        )

        await member.create_secrets(members_ca=service.members_ca)

        member.data_secret.create_shared_key()

        member.schema = await member.load_schema(
            os.path.split(DEFAULT_SCHEMA)[-1],
            verify_signatures=False
        )

        member.data = MemberData(
            member, member.paths, member.document_store
        )
        await member.data.save_protected_shared_key()
        member.data.initalize()
        await member.data.save()

        app = Starlette(debug=True)
        graphql_app = GraphQL(member.schema.gql_schema, debug=True)
        for path in ['/', '/graphql']:
            app.add_route(path, graphql_app)

        TestJsonSchema.PROCESS = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={
                'host': '0.0.0.0',
                'port': server.HTTP_PORT,
                'log_level': 'info'
            },
            daemon=True
        )
        TestJsonSchema.PROCESS.start()
        await asyncio.sleep(3)

    @classmethod
    def tearDownClass(cls):
        TestJsonSchema.PROCESS.terminate()

    def test_jsonschema(self):
        with open(DEFAULT_SCHEMA) as fd:
            data = fd.read()
            fastjson_schema = orjson.loads(data)

        validate = fastjsonschema.compile(fastjson_schema)

        test = validate(data)
        self.assertEqual(data, test)

        member_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={MEMBER_ID}.members-{SERVICE_ID}.{NETWORK}',
            'X-Client-SSL-Issuing-CA': f'CN=members-ca.{NETWORK}'
        }

        client = GraphqlClient(endpoint=BASE_URL)

        result = client.execute(query=member_query, headers=member_headers)
        self.assertEqual(result['data']['member']['member_id'], str(MEMBER_ID))

        person_variables = {
            'given_name': 'Peter',
            'additional_names': '',
            'family_name': 'Hessing',
            'email': 'steven@byoda.org',
            'homepage_url': 'https://some.place/',
            'avatar_url': 'https://some.place/avatar'
        }
        result = client.execute(
            query=person_mutation, headers=member_headers,
            variables=person_variables
        )

        result = client.execute(query=person_query, headers=member_headers)
        self.assertEqual(
            result['data']['person']['given_name'],
            person_variables['given_name']
        )

        result = client.execute(query=memberlogs_query, headers=member_headers)
        self.assertEqual(result['data']['memberlogs'], [])

        memberlog_variables = {
            'timestamp': '2022-01-21T04:01:36.798843+00:00',
            'remote_addr': '10.0.0.1',
            'action': 'join',
            'message': 'blah'
        }
        result = client.execute(
            query=memberlogs_mutation, headers=member_headers,
            variables=memberlog_variables
        )
        self.assertEqual(
            result['data']['append_memberlogs']['remote_addr'],
            memberlog_variables['remote_addr']
        )

        result = client.execute(query=memberlogs_query, headers=member_headers)
        self.assertEqual(len(result['data']['memberlogs']), 1)
        self.assertEqual(
            result['data']['memberlogs'][0]['remote_addr'],
            memberlog_variables['remote_addr']
        )

        memberlog_variables = {
            'timestamp': '2022-01-24T04:01:36.798843+00:00',
            'remote_addr': '10.0.0.2',
            'action': 'leave',
            'message': 'bye bye'
        }
        result = client.execute(
            query=memberlogs_mutation, headers=member_headers,
            variables=memberlog_variables
        )
        self.assertEqual(
            result['data']['append_memberlogs']['remote_addr'],
            memberlog_variables['remote_addr']
        )

        result = client.execute(query=memberlogs_query, headers=member_headers)
        self.assertEqual(len(result['data']['memberlogs']), 2)

        result = client.execute(
            query=network_links_query, headers=member_headers
        )
        self.assertEqual(result['data']['network_links'], [])

        network_links_variables = {
            'timestamp': '2022-01-21T04:01:36.798843+00:00',
            'member_id': 'af0b7314-7df7-11ec-ab86-00155d0d2987',
            'relation': 'friend'
        }

        result = client.execute(
            query=network_links_mutation, headers=member_headers,
            variables=network_links_variables
        )
        self.assertEqual(
            result['data']['append_network_links']['relation'],
            network_links_variables['relation']
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
