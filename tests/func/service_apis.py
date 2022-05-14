#!/usr/bin/env python3

'''
Test the Directory APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import sys
import os
import yaml
import shutil
import asyncio
import unittest
import requests
from uuid import uuid4

from multiprocessing import Process
import uvicorn

from cryptography.hazmat.primitives import serialization

from byoda.datamodel.network import Network
from byoda.datamodel.schema import Schema
from byoda.servers.service_server import ServiceServer
from byoda.datamodel.service import Service

from byoda.secrets import Secret
from byoda.secrets import MemberSecret
from byoda.secrets import MemberDataSecret

from byoda.util.logger import Logger
from byoda.util.paths import Paths

from byoda import config

from byoda.util.fastapi import setup_api

from svcserver.routers import service
from svcserver.routers import member

# Settings must match config.yml used by directory server
TEST_DIR = '/tmp/byoda-test/svc-apis'
NETWORK = 'test.net'
DUMMY_SCHEMA = 'tests/collateral/dummy-unsigned-service-schema.json'
SERVICE_ID = 12345678

CONFIG_FILE = 'tests/collateral/config.yml'
TEST_PORT = 5000
BASE_URL = f'http://localhost:{TEST_PORT}/api'

_LOGGER = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        with open(CONFIG_FILE) as file_desc:
            TestDirectoryApis.APP_CONFIG = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        app_config = TestDirectoryApis.APP_CONFIG

        app_config['svcserver']['service_id'] = SERVICE_ID
        app_config['svcserver']['root_dir'] = TEST_DIR

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        service_dir = (
            f'{TEST_DIR}/network-'
            f'{app_config["application"]["network"]}'
            f'/services/service-{SERVICE_ID}'
        )
        os.makedirs(service_dir)

        network = await Network.create(
            app_config['application']['network'],
            TEST_DIR,
            app_config['svcserver']['private_key_password']
        )
        await network.load_network_secrets()

        service_file = network.paths.get(
            Paths.SERVICE_FILE, service_id=SERVICE_ID
        )

        shutil.copy(DUMMY_SCHEMA, TEST_DIR + '/' + service_file)

        svc = Service(
            network, service_file,
            app_config['svcserver']['service_id']
        )
        await svc.create_secrets(
            network.services_ca, local=True,
            password=app_config['svcserver']['private_key_password']
        )

        config.server = ServiceServer(app_config)

        config.server.load_secrets(
            app_config['svcserver']['private_key_password']
        )
        config.server.load_schema(verify_contract_signatures=False)

        app = setup_api(
            'Byoda test svcserver', 'server for testing service APIs',
            'v0.0.1', None, [], [service, member]
        )
        TestDirectoryApis.PROCESS = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={
                'host': '127.0.0.1',
                'port': TEST_PORT,
                'log_level': 'debug'
            },
            daemon=True
        )
        TestDirectoryApis.PROCESS.start()
        asyncio.sleep(1)

    @classmethod
    def tearDownClass(cls):
        cls.PROCESS.terminate()

    def test_service_get(self):
        API = BASE_URL + f'/v1/service/service/{SERVICE_ID}'

        response = requests.get(API)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 10)
        self.assertEqual(data['service_id'], SERVICE_ID)
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['name'], 'dummyservice')
        # Schema is not signed for this test case
        # self.assertEqual(len(data['signatures']), 2)
        schema = Schema(data)           # noqa: F841

    def test_member_putpost(self):
        API = BASE_URL + '/v1/service/member'

        service = config.server.service

        member_id = uuid4()

        # HACK: MemberSecret takes an Account instance as third parameter but
        # we use a Service instance instead
        service.paths.account = 'pod'
        secret = MemberSecret(member_id, SERVICE_ID, service)
        csr = secret.create_csr()
        csr = csr.public_bytes(serialization.Encoding.PEM)

        response = requests.post(
            API, json={'csr': str(csr, 'utf-8')}, headers=None
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()

        self.assertTrue('signed_cert' in data)
        self.assertTrue('cert_chain' in data)
        self.assertTrue('service_data_cert_chain' in data)

        signed_secret = MemberSecret(member_id, SERVICE_ID, service)
        signed_secret.from_string(
            data['signed_cert'], certchain=data['cert_chain']
        )

        service_data_cert_chain = secret.from_string(       # noqa: F841
            data['service_data_cert_chain']
        )

        membersecret_commonname = Secret.extract_commonname(signed_secret.cert)
        memberscasecret_commonname = Secret.extract_commonname(
            signed_secret.cert_chain[0]
        )

        # PUT, with auth
        # In the PUT body we put the member data secret as a service may
        # have use for it in the future.
        member_data_secret = MemberDataSecret(member_id, SERVICE_ID, service)
        csr = member_data_secret.create_csr()
        cert_chain = service.members_ca.sign_csr(csr)
        member_data_secret.from_signed_cert(cert_chain)
        member_data_certchain = member_data_secret.certchain_as_pem()

        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={membersecret_commonname}',
            'X-Client-SSL-Issuing-CA':
                f'CN={memberscasecret_commonname}'
        }
        response = requests.put(
            f'{API}/version/1', headers=headers,
            json={'certchain': member_data_certchain}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ipv4_address'], '127.0.0.1')
        self.assertEqual(data['ipv6_address'], None)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
