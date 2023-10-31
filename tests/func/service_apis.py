#!/usr/bin/env python3

'''
Test the Directory APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import os
import yaml
import shutil
import asyncio
import unittest
import httpx
from uuid import uuid4

from multiprocessing import Process
import uvicorn

from cryptography.hazmat.primitives import serialization

from byoda.datamodel.account import Account
from byoda.datamodel.network import Network
from byoda.datamodel.schema import Schema
from byoda.datamodel.service import Service

from byoda.secrets.secret import Secret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.storage.filestorage import FileStorage

from byoda.servers.service_server import ServiceServer

from byoda.util.logger import Logger
from byoda.util.paths import Paths

from byoda import config

from byoda.util.fastapi import setup_api

from svcserver.routers import service as ServiceRouter
from svcserver.routers import member as MemberRouter
from svcserver.routers import search as SearchRouter
from svcserver.routers import status as StatusRouter

from tests.lib.util import get_test_uuid

# Settings must match config.yml used by directory server
TEST_DIR = '/tmp/byoda-tests/svc-apis'
NETWORK = 'test.net'
DUMMY_SCHEMA = 'tests/collateral/dummy-unsigned-service-schema.json'
SERVICE_ID = 12345678

CONFIG_FILE = 'tests/collateral/config.yml'
TEST_PORT = 8000
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

        service_file = network.paths.get(
            Paths.SERVICE_FILE, service_id=SERVICE_ID
        )

        shutil.copy(DUMMY_SCHEMA, TEST_DIR + '/' + service_file)

        svc = Service(
            network=network, service_id=app_config['svcserver']['service_id']
        )
        if service_file:
            await svc.examine_servicecontract(service_file)

        await svc.create_secrets(
            network.services_ca, local=True,
            password=app_config['svcserver']['private_key_password']
        )

        config.server = ServiceServer(network, app_config)
        storage = FileStorage(app_config['svcserver']['root_dir'])
        await config.server.load_network_secrets(storage_driver=storage)

        await config.server.load_secrets(
            app_config['svcserver']['private_key_password']
        )
        await config.server.load_schema(verify_contract_signatures=False)

        config.trace_server: str = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        app = setup_api(
            'Byoda test svcserver', 'server for testing service APIs',
            'v0.0.1',
            [ServiceRouter, MemberRouter, SearchRouter, StatusRouter],
            lifespan=None, trace_server=config.trace_server,
        )

        TestDirectoryApis.PROCESS = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={
                'host': '0.0.0.0',
                'port': TEST_PORT,
                'log_level': 'debug'
            },
            daemon=True
        )
        TestDirectoryApis.PROCESS.start()
        await asyncio.sleep(1)

    @classmethod
    async def asyncTDown(self):
        TestDirectoryApis.PROCESS.terminate()

    def test_service_get(self):
        API = BASE_URL + f'/v1/service/service/{SERVICE_ID}'

        response = httpx.get(API)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 12)
        self.assertEqual(data['service_id'], SERVICE_ID)
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['name'], 'dummyservice')
        # Schema is not signed for this test case
        # self.assertEqual(len(data['signatures']), 2)
        schema = Schema(data)           # noqa: F841

    async def test_member_putpost(self):
        API = BASE_URL + '/v1/service/member'

        service = config.server.service

        member_id = uuid4()

        # HACK: MemberSecret takes an Account instance as third parameter but
        # we use a Service instance instead
        service.paths.account = 'pod'
        secret = MemberSecret(member_id, SERVICE_ID, service)
        csr = await secret.create_csr()
        csr = csr.public_bytes(serialization.Encoding.PEM)

        response = httpx.post(
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
        pod_account = Account(uuid4(), service.network)
        member_data_secret = MemberDataSecret(
            member_id, SERVICE_ID, pod_account
        )
        csr = await member_data_secret.create_csr()
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
        response = httpx.put(
            f'{API}/version/1', headers=headers,
            json={'certchain': member_data_certchain}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ipv4_address'], '127.0.0.1')
        self.assertEqual(data['ipv6_address'], None)

        asset_id = str(get_test_uuid())
        API = BASE_URL + '/v1/service/search/asset'
        response = httpx.post(
            API, headers=headers, json={
                'hashtags': ['gaap'],
                'mentions': ['blah'],
                'nickname': None,
                'text': None,
                'asset_id': asset_id
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertTrue(
            membersecret_commonname.startswith(data[0]['member_id'])
        )
        self.assertEqual(asset_id, data[0]['asset_id'])

        # TODO: see how we can use json parameter with httpx.get()
        import requests
        response = requests.get(
            API, headers=headers, json={
                'mentions': ['blah']
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data), 3)
        self.assertTrue(
            membersecret_commonname.startswith(data[-1]['member_id'])
        )
        self.assertEqual(asset_id, data[-1]['asset_id'])

        response = httpx.get(
            API, headers=headers, json={
                'mentions': ['blah']
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        total_items = len(data)

        response = httpx.delete(
            API, headers=headers, json={
                'hashtags': None,
                'mentions': ['blah'],
                'nickname': None,
                'text': None,
                'asset_id': asset_id
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertTrue(
            membersecret_commonname.startswith(data[0]['member_id'])
        )
        self.assertEqual(asset_id, data[0]['asset_id'])

        response = httpx.get(
            API, headers=headers, json={
                'mentions': ['blah']
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), total_items - 1)


if __name__ == '__main__':
    unittest.main()
