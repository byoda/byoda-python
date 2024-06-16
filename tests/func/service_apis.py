#!/usr/bin/env python3

'''
Test the Service APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

import sys
import os
import yaml
import shutil
import unittest

from httpx import Response
from httpx import AsyncClient
from uuid import UUID

from fastapi import FastAPI

from cryptography.hazmat.primitives import serialization

from byoda.datamodel.account import Account
from byoda.datamodel.network import Network
from byoda.datamodel.schema import Schema
from byoda.datamodel.service import Service
from byoda.secrets.membersca_secret import MembersCaSecret

from byoda.storage.filestorage import FileStorage

from byoda.secrets.secret import Secret
from byoda.secrets.secret import CertChain
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_secret import CertificateSigningRequest
from byoda.secrets.member_data_secret import MemberDataSecret

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
TEST_DIR: str = '/tmp/byoda-tests/svc-apis'
NETWORK: str = 'test.net'
DUMMY_SCHEMA: str = 'tests/collateral/dummy-unsigned-service-schema.json'
SERVICE_ID: int = 12345678

CONFIG_FILE: str = 'tests/collateral/config.yml'
TEST_PORT: int = 8000
BASE_URL: str = f'http://localhost:{TEST_PORT}/api'

APP: FastAPI | None = None

_LOGGER = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS: int | None = None
    APP_CONFIG: dict[str, any] | None = None

    async def asyncSetUp(self) -> None:
        with open(CONFIG_FILE) as file_desc:
            TestDirectoryApis.APP_CONFIG = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        app_config: dict[str, any] = TestDirectoryApis.APP_CONFIG

        app_config['svcserver']['service_id'] = SERVICE_ID
        app_config['svcserver']['root_dir'] = TEST_DIR

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        service_dir: str = (
            f'{TEST_DIR}/network-'
            f'{app_config["application"]["network"]}'
            f'/services/service-{SERVICE_ID}'
        )
        os.makedirs(service_dir)

        network: Network = await Network.create(
            app_config['application']['network'],
            TEST_DIR,
            app_config['svcserver']['private_key_password']
        )

        service_file: str = network.paths.get(
            Paths.SERVICE_FILE, service_id=SERVICE_ID
        )

        shutil.copy(DUMMY_SCHEMA, TEST_DIR + '/' + service_file)

        service = Service(
            network=network, service_id=app_config['svcserver']['service_id']
        )
        if service_file:
            await service.examine_servicecontract(service_file)

        await service.create_secrets(
            network.services_ca, local=True,
            password=app_config['svcserver']['private_key_password']
        )

        server: ServiceServer = await ServiceServer.setup(network, app_config)
        config.server = server

        storage = FileStorage(app_config['svcserver']['root_dir'])
        await config.server.load_network_secrets(storage_driver=storage)

        await config.server.load_secrets(
            app_config['svcserver']['private_key_password']
        )

        await server.load_schema(verify_contract_signatures=False)

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        global APP
        APP = setup_api(
            'Byoda test svcserver', 'server for testing service APIs',
            'v0.0.1',
            [
                ServiceRouter,
                MemberRouter,
                SearchRouter,
                StatusRouter,
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        # TestDirectoryApis.PROCESS = Process(
        #     target=uvicorn.run,
        #     args=(APP,),
        #     kwargs={
        #         'host': '0.0.0.0',
        #         'port': TEST_PORT,
        #         'log_level': 'debug'
        #     },
        #     daemon=True
        # )
        # TestDirectoryApis.PROCESS.start()
        # await sleep(1)

    @classmethod
    async def asyncTearDown(self) -> None:
        # TestDirectoryApis.PROCESS.terminate()
        pass

    async def test_service_get(self) -> None:
        API: str = BASE_URL + f'/v1/service/service/{SERVICE_ID}'

        async with AsyncClient(app=APP) as client:
            response: Response = await client.get(API, timeout=300)
        self.assertEqual(response.status_code, 200)
        data: dict[str, any] = response.json()
        self.assertEqual(len(data), 12)
        self.assertEqual(data['service_id'], SERVICE_ID)
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['name'], 'dummyservice')
        # Schema is not signed for this test case
        # self.assertEqual(len(data['signatures']), 2)
        Schema(data)           # noqa: F841

    async def test_member_putpost(self) -> None:
        API: str = BASE_URL + '/v1/service/member'

        service: Service = config.server.service

        member_id: UUID = get_test_uuid()

        # HACK: MemberSecret takes an Account instance as third parameter but
        # we use a Service instance instead
        pod_account = Account(get_test_uuid(), service.network)
        secret = MemberSecret(member_id, SERVICE_ID, pod_account)
        csr = await secret.create_csr()
        csr = csr.public_bytes(serialization.Encoding.PEM)

        async with AsyncClient(app=APP) as client:
            response: Response = await client.post(
                API, json={'csr': str(csr, 'utf-8')}, headers=None,
                timeout=300
            )
        self.assertEqual(response.status_code, 201)
        data = response.json()

        self.assertTrue('signed_cert' in data)
        self.assertTrue('cert_chain' in data)
        self.assertTrue('service_data_cert_chain' in data)

        signed_secret = MemberSecret(
            member_id, SERVICE_ID, paths=service.paths,
            network_name=service.network.name
        )
        signed_secret.from_string(
            data['signed_cert'], certchain=data['cert_chain']
        )

        service_data_cert_chain: None = secret.from_string(       # noqa: F841
            data['service_data_cert_chain']
        )

        membersecret_commonname: str = Secret.extract_commonname(
            signed_secret.cert
        )
        memberscasecret_commonname: str = Secret.extract_commonname(
            signed_secret.cert_chain[0]
        )

        # PUT, with auth
        # In the PUT body we put the member data secret as a service may
        # have use for it in the future.
        pod_account = Account(get_test_uuid(), service.network)
        member_data_secret = MemberDataSecret(
            member_id, SERVICE_ID, pod_account
        )
        csr: CertificateSigningRequest = await member_data_secret.create_csr()
        members_ca: MembersCaSecret = service.members_ca
        cert_chain: CertChain = members_ca.sign_csr(csr)
        member_data_secret.from_signed_cert(cert_chain)
        member_data_certchain: str = member_data_secret.certchain_as_pem()

        headers: dict[str, str] = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={membersecret_commonname}',
            'X-Client-SSL-Issuing-CA':
                f'CN={memberscasecret_commonname}'
        }
        async with AsyncClient(app=APP) as client:

            response: Response = await client.put(
                f'{API}/version/1', headers=headers,
                json={'certchain': member_data_certchain},
                timeout=300
            )

            self.assertEqual(response.status_code, 200)
            data: any = response.json()
            self.assertEqual(data['ipv4_address'], '127.0.0.1')
            self.assertEqual(data['ipv6_address'], None)


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
