#!/usr/bin/env python3

'''
Test the Directory APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license
'''

import sys
import os
import yaml
import orjson
import shutil
import asyncio
from copy import copy
from uuid import uuid4
from uuid import UUID

import httpx
import unittest

import uvicorn

from cryptography import x509
from cryptography.x509 import Certificate
from cryptography.hazmat.primitives import serialization

from multiprocessing import Process

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

from fastapi import FastAPI

from byoda.datamodel.network import Network
from byoda.datamodel.schema import Schema

from byoda.servers.directory_server import DirectoryServer

from byoda.util.message_signature import SignatureType

from byoda.secrets.secret import Secret
from byoda.secrets.secret import CertChain
from byoda.secrets.account_secret import CertificateSigningRequest
from byoda.secrets.account_secret import AccountSecret
from byoda.secrets.serviceca_secret import ServiceCaSecret
from byoda.secrets.service_secret import ServiceSecret
from byoda.secrets.service_data_secret import ServiceDataSecret

from byoda.storage.filestorage import FileStorage

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from byoda.util.fastapi import setup_api

from dirserver.routers import account as AccountRouter
from dirserver.routers import service as ServiceRouter
from dirserver.routers import member as MemberRouter

# Settings must match config.yml used by directory server
NETWORK: str = 'test.net'
DEFAULT_SCHEMA: str = 'tests/collateral/dummy-unsigned-service-schema.json'
SERVICE_ID: int = 12345678

CONFIG_FILE: str = 'tests/collateral/config.yml'
TEST_DIR: str = '/tmp/byoda-tests/dir_apis'
SERVICE_DIR: str = TEST_DIR + '/service'
TEST_PORT: int = 9000
BASE_URL: str = f'http://localhost:{TEST_PORT}/api'

_LOGGER = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self) -> None:
        ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

        with open(CONFIG_FILE) as file_desc:
            TestDirectoryApis.APP_CONFIG: dict[str, any] = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        await delete_test_data()

        app_config: dict[str, any] = TestDirectoryApis.APP_CONFIG
        app_config['dirserver']['root_dir'] = TEST_DIR

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)
        os.makedirs(
            f'{SERVICE_DIR}/network-{app_config["application"]["network"]}'
            f'/services/service-{SERVICE_ID}'
        )

        network: Network = await Network.create(
            app_config['application']['network'],
            app_config['dirserver']['root_dir'],
            app_config['dirserver']['private_key_password'],
        )

        config.server = DirectoryServer(network)
        await config.server.connect_db(app_config['dirserver']['dnsdb'])

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server)

        app: FastAPI = setup_api(
            'Byoda test dirserver', 'server for testing directory APIs',
            'v0.0.1', [AccountRouter, ServiceRouter, MemberRouter],
            lifespan=None, trace_server=config.trace_server,
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
        await asyncio.sleep(1)

    @classmethod
    async def asyncTearDown(cls) -> None:
        TestDirectoryApis.PROCESS.terminate()

    def test_network_account_put(self) -> None:
        api: str = BASE_URL + '/v1/network/account'

        uuid: UUID = uuid4()

        network_name: str = \
            TestDirectoryApis.APP_CONFIG['application']['network']

        # PUT, with auth
        headers: dict[str, str] = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={uuid}.accounts.{network_name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network_name}'
        }
        response: httpx.Response = httpx.put(api, headers=headers)
        self.assertEqual(response.status_code, 200)
        data: any = response.json()
        self.assertEqual(data['ipv4_address'], '127.0.0.1')
        self.assertIsNone(data['ipv6_address'])

    async def test_network_account_post(self) -> None:
        # These tests require a running directory server
        return
        api: str = BASE_URL + '/v1/network/account'

        network = Network(
            TestDirectoryApis.APP_CONFIG['dirserver'],
            TestDirectoryApis.APP_CONFIG['application']
        )
        storage = FileStorage(
            TestDirectoryApis.APP_CONFIG['svcserver']['root_dir']
        )
        await network.load_network_secrets(storage_driver=storage)

        uuid: UUID = uuid4()
        secret = AccountSecret(account_id=uuid, network=network)
        csr = await secret.create_csr()
        csr: bytes = csr.public_bytes(serialization.Encoding.PEM)
        fqdn: str = AccountSecret.create_commonname(uuid, network.name)
        headers: dict[str, str] = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={fqdn}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.name}'
        }
        response: httpx.Response = httpx.post(
            api, json={'csr': str(csr, 'utf-8')}, headers=headers
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        issuing_ca_cert: Certificate = x509.load_pem_x509_certificate(       # noqa:F841
            data['cert_chain'].encode()
        )
        account_cert: Certificate = x509.load_pem_x509_certificate(          # noqa:F841
            data['signed_cert'].encode()
        )
        network_data_cert: Certificate = x509.load_pem_x509_certificate(     # noqa:F841
            data['network_data_cert_chain'].encode()
        )

        # Retry same CSR, with same TLS client cert:
        response = httpx.post(
            api, json={'csr': str(csr, 'utf-8')}, headers=headers
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        issuing_ca_cert = x509.load_pem_x509_certificate(       # noqa:F841
            data['cert_chain'].encode()
        )
        account_cert = x509.load_pem_x509_certificate(          # noqa:F841
            data['signed_cert'].encode()
        )
        network_data_cert = x509.load_pem_x509_certificate(     # noqa:F841
            data['network_data_cert_chain'].encode()
        )

        # Retry same CSR, without client cert:
        response: httpx.Response = httpx.post(
            api, json={'csr': str(csr, 'utf-8')}, headers=None
        )
        self.assertEqual(response.status_code, 401)

    async def test_network_service_creation(self) -> None:
        api: str = BASE_URL + '/v1/network/service'

        # We can not use deepcopy here so do two copies
        network: Network = copy(config.server.network)
        network.paths = copy(config.server.network.paths)
        network.paths._root_directory = SERVICE_DIR
        if not await network.paths.secrets_directory_exists():
            await network.paths.create_secrets_directory()

        service_id: int = SERVICE_ID
        serviceca_secret = ServiceCaSecret(
            service_id=service_id, network=network
        )
        csr = await serviceca_secret.create_csr()
        csr: bytes = csr.public_bytes(serialization.Encoding.PEM)

        response: httpx.Response = httpx.post(
            api, json={'csr': str(csr, 'utf-8')}
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        issuing_ca_cert: Certificate = x509.load_pem_x509_certificate(
            data['cert_chain'].encode()
        )
        serviceca_cert: Certificate = x509.load_pem_x509_certificate(
            data['signed_cert'].encode()
        )
        # TODO: populate a secret from a CertChain
        serviceca_secret.cert = serviceca_cert
        serviceca_secret.cert_chain = [issuing_ca_cert]
        network_data_cert: Certificate = x509.load_pem_x509_certificate(
            data['network_data_cert_chain'].encode()
        )

        # Check that the service CA public cert was written to the network
        # directory of the dirserver
        testsecret = ServiceCaSecret(
            service_id=service_id, network=config.server.network
        )
        await testsecret.load(with_private_key=False)

        service_secret = ServiceSecret(service_id, network)
        service_csr: CertificateSigningRequest = \
            await service_secret.create_csr()
        certchain: CertChain = serviceca_secret.sign_csr(service_csr)
        service_secret.from_signed_cert(certchain)
        await service_secret.save()

        service_cn: str = Secret.extract_commonname(certchain.signed_cert)
        serviceca_cn: str = Secret.extract_commonname(serviceca_cert)

        # Create and register the the public cert of the data secret,
        # which the directory server needs to validate the service signature
        # of the schema for the service
        service_data_secret = ServiceDataSecret(
            service_id, network
        )
        service_data_csr: CertificateSigningRequest =\
            await service_data_secret.create_csr()
        data_certchain: CertChain = serviceca_secret.sign_csr(service_data_csr)
        service_data_secret.from_signed_cert(data_certchain)
        await service_data_secret.save()

        headers: dict[str, str] = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={service_cn}',
            'X-Client-SSL-Issuing-CA': f'CN={serviceca_cn}'
        }

        data_certchain = service_data_secret.certchain_as_pem()

        response: httpx.Response = httpx.put(
            api + '/service_id/' + str(service_id), headers=headers,
            json={'certchain': data_certchain}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ipv4_address'], '127.0.0.1')

        # Send the service schema
        with open(DEFAULT_SCHEMA) as file_desc:
            data: str = file_desc.read()
            schema_data = orjson.loads(data)

        schema_data['service_id'] = service_id
        schema_data['version'] = 1

        schema = Schema(schema_data)
        schema.create_signature(service_data_secret, SignatureType.SERVICE)

        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={service_cn}',
            'X-Client-SSL-Issuing-CA': f'CN={serviceca_cn}'
        }

        response = httpx.patch(
            api + f'/service_id/{service_id}', headers=headers,
            json=schema.json_schema
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ACCEPTED')
        self.assertEqual(len(data['errors']), 0)

        # Get the fully-signed data contract for the service
        api = BASE_URL + '/v1/network/service'

        response: httpx.Response = httpx.get(api + f'/service_id/{service_id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 12)
        self.assertEqual(data['service_id'], SERVICE_ID)
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['name'], 'dummyservice')
        self.assertEqual(len(data['signatures']), 2)
        schema = Schema(data)

        # Get the list of service summaries
        api = BASE_URL + '/v1/network/services'
        response = httpx.get(api)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        service_summary: str = data['service_summaries'][0]
        self.assertEqual(service_summary['service_id'], SERVICE_ID)
        self.assertEqual(service_summary['version'], 1)
        self.assertEqual(service_summary['name'], 'dummyservice')

        # Now test membership registration against the directory server
        api: str = BASE_URL + '/v1/network/member'

        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={uuid4()}.members-{service_id}.{network.name}',
            'X-Client-SSL-Issuing-CA':
            f'CN=members-ca.members-ca-{service_id}.{network.name}'
        }

        response: httpx.Response = httpx.put(api, headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ipv4_address'], '127.0.0.1')


async def delete_test_data() -> None:
    with open(CONFIG_FILE) as file_desc:
        config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    global TEST_NETWORK
    TEST_NETWORK = config['application']['network']

    connection_string: str = config['dirserver']['dnsdb']
    pool: AsyncConnectionPool = AsyncConnectionPool(
        conninfo=connection_string, open=False,
        kwargs={'row_factory': dict_row}
    )
    await pool.open()

    async with pool.connection() as conn:
        await conn.execute(
            'DELETE FROM domains WHERE name != %s', [f'{TEST_NETWORK}']
        )

        await conn.execute(
            'DELETE FROM records WHERE name != %s', [f'{TEST_NETWORK}']
        )

    await pool.close()


if __name__ == '__main__':
    _LOGGER = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
