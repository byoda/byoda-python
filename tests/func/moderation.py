#!/usr/bin/env python3

'''
Test the Moderation APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license
'''

import os
import sys
import yaml
import shutil
import asyncio
import unittest

from typing import TypeVar

from multiprocessing import Process

import uvicorn

from fastapi import FastAPI

from byoda.datamodel.network import Network
from byoda.datastore.document_store import DocumentStoreType


from byoda.servers.app_server import AppServer

from byoda.datatypes import CloudType
from byoda.datatypes import ClaimStatus
from byoda.datatypes import IdType

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.api_client import HttpMethod
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda import config

from byoda.util.fastapi import setup_api

from tests.lib.defines import COLLATERAL_DIR
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.util import get_test_uuid

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars

from modserver.routers import moderate as ModerateRouter
from modserver.routers import status as StatusRouter

Member = TypeVar('Member')

CONFIG_FILE: str = 'tests/collateral/local/config-mod.yml'
TEST_DIR: str = '/tmp/byoda-tests/mod_apis'
TEST_PORT: int = 8000
BASE_URL: str = f'http://localhost:{TEST_PORT}/api/v1'

TEST_APP_ID: str = '05cbb871-ee50-4ba5-8dda-4879142fb67e'

_LOGGER: Logger

APP: FastAPI | None = None


class TestApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        config.debug = True
        config.tls_cert_file = '/tmp/cert.pem'
        with open(CONFIG_FILE) as file_desc:
            TestApis.APP_CONFIG = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        app_config = TestApis.APP_CONFIG
        app_config['appserver']['root_dir'] = TEST_DIR
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(app_config['appserver']['whitelist_dir'], exist_ok=True)

        claim_dir = app_config['appserver']['claim_dir']
        for status in ClaimStatus:
            os.makedirs(f'{claim_dir}/{status.value}', exist_ok=True)

        paths = {
            'key': '/private/network-byoda.net/service-4294929430/apps/',
            'pem': '/network-byoda.net/service-4294929430/apps/'
        }
        os.makedirs(f'{TEST_DIR}{paths["key"]}', exist_ok=True)
        os.makedirs(f'{TEST_DIR}{paths["pem"]}', exist_ok=True)
        files = (
            f'app-{TEST_APP_ID}-cert.pem', f'app-data-{TEST_APP_ID}-cert.pem',
            f'app-{TEST_APP_ID}.key', f'app-data-{TEST_APP_ID}.key'
        )
        for file in files:
            file_type = file[-3:]
            filepath = paths[file_type] + file
            shutil.copyfile(
                f'{COLLATERAL_DIR}/local/{file}',
                f'{TEST_DIR}{filepath}'
            )

        network = Network(
            app_config['appserver'], app_config['application']
        )

        server = AppServer(
            app_config['appserver']['app_id'], network, app_config
        )

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType.LOCAL,
            private_bucket='byoda',
            restricted_bucket='byoda',
            public_bucket='byoda',
            root_dir=app_config['appserver']['root_dir']
        )

        config.server = server

        await network.load_network_secrets()

        await server.load_secrets(
            password=app_config['appserver']['private_key_password']
        )

        if not os.environ.get('SERVER_NAME') and config.server.network.name:
            os.environ['SERVER_NAME'] = config.server.network.name

        config.trace_server: str = os.environ.get(
            'TRACE_SERVER', config.trace_server)

        global APP
        APP = setup_api(
            'Byoda moderation server', 'server for moderation APIs',
            'v0.0.1', [StatusRouter, ModerateRouter], lifespan=None,
            trace_server=config.trace_server
        )
        TestApis.PROCESS = Process(
            target=uvicorn.run,
            args=(APP,),
            kwargs={
                'host': '127.0.0.1',
                'port': TEST_PORT,
                'log_level': 'debug'
            },
            daemon=True
        )
        TestApis.PROCESS.start()
        await asyncio.sleep(2)

    @classmethod
    async def asyncTearDown(cls):
        await ApiClient.close_all()
        TestApis.PROCESS.terminate()

    async def test_moderation_asset_post_jwt(self):
        API = BASE_URL + '/moderate/asset'
        server: AppServer = config.server

        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)
        account = await setup_account(network_data)

        member: Member = await account.get_membership(ADDRESSBOOK_SERVICE_ID)

        with open(config.tls_cert_file, 'wb') as file_desc:
            file_desc.write(member.tls_secret.cert_as_pem())

        network_name = TestApis.APP_CONFIG['application']['network']

        claim_data = {
            'claims': ['blah 5', 'gaap 4'],
            'claim_data': {
                'asset_id': '3f293e6d-65a8-41c6-887d-6c6260aea8b8',
                'asset_type': 'public_assets',
                'asset_url': 'https://cdn.byoda.io/restricted/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/video.mpd',      # noqa: E501
                'asset_merkle_root_hash':
                    'JM/gRbo5diTfTkuVLTPCjDE4ZWTwXRwHH8pwlJKkCXM=',
                'public_video_thumbnails': [
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/maxresdefault.webp',          # noqa: E501
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/default.jpg',                 # noqa: E501
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/mqdefault.jpg',               # noqa: E501
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/hqdefault.jpg',               # noqa: E501
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/hqdefault.jpg',               # noqa: E501
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/hqdefault.jpg',               # noqa: E501
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/hqdefault.jpg',               # noqa: E501
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/hqdefault.jpg',               # noqa: E501
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/sddefault.jpg',               # noqa: E501
                    'https://cdn.byoda.io/public/4294929430/94f23c4b-1721-4ffe-bfed-90f86d07611a/3f293e6d-65a8-41c6-887d-6c6260aea8b8/maxresdefault.jpg',           # noqa: E501
                ],
                'creator': 'Dathes',
                'publisher': 'NotYouTube',
                'publisher_asset_id': '5Y9L5NBINV4',
                'title': 'Big Buck Bunny',
                'contents': '',
                'annotations': [],
            }
        }

        ssl_headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={member.member_id}.members-{ADDRESSBOOK_SERVICE_ID}.{network_name}',      # noqa: E501
            'X-Client-SSL-Issuing-CA':
                (
                    'CN=members-ca.members-ca-'
                    f'{ADDRESSBOOK_SERVICE_ID}.{network_name}'
                )
        }

        #
        # Test with SSL headers
        #
        resp: HttpResponse = await RestApiClient.call(
            API, method=HttpMethod.POST, headers=ssl_headers, data=claim_data,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'pending')
        self.assertIsNone(data['signature'])
        self.assertIsNotNone(data['request_id'])
        request_file = server.get_claim_filepath(
            ClaimStatus.PENDING, data['request_id']
        )
        self.assertTrue(os.path.exists(request_file))

        #
        # Test with JWT
        #
        jwt = member.create_jwt(target_id=TEST_APP_ID, target_type=IdType.APP)
        jwt_headers = {'Authorization': f'bearer {jwt.encoded}'}

        # Make sure asset_id is unique
        claim_data['claim_data']['asset_id'] = str(get_test_uuid())
        resp = await RestApiClient.call(
            API, HttpMethod.POST, headers=jwt_headers, data=claim_data,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'pending')
        self.assertIsNone(data['signature'])
        self.assertIsNotNone(data['request_id'])
        request_file = server.get_claim_filepath(
            ClaimStatus.PENDING, data['request_id']
        )
        self.assertTrue(os.path.exists(request_file))

        #
        # Test with SSL headers and YouTube asset
        #
        claim_data['claim_data']['publisher'] = 'YouTube'
        claim_data['claim_data']['asset_id'] = str(get_test_uuid())
        resp = await RestApiClient.call(
            API, method=HttpMethod.POST, headers=ssl_headers, data=claim_data,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data['request_id'])
        self.assertEqual(data['status'], 'accepted')
        self.assertIsNotNone(data['signature'])
        self.assertIsNotNone(data['signature_timestamp'])
        self.assertIsNotNone(data['issuer_id'])
        self.assertIsNotNone(data['issuer_type'])
        self.assertIsNotNone(data['cert_fingerprint'])
        self.assertIsNotNone(data['cert_expiration'])

        claim_file = server.get_claim_filepath(
            ClaimStatus.ACCEPTED, claim_data['claim_data']['asset_id']
        )
        self.assertTrue(os.path.exists(claim_file))

        #
        # Test with SSL headers and whitelisted member
        #
        claim_data['claim_data']['publisher'] = 'NotYouTube'
        whitelist_file = f'{server.whitelist_dir}/{member.member_id}'
        with open(whitelist_file, 'w') as file_desc:
            file_desc.write('{"creator": "tests/func/moderation.py"}')

        claim_data['claim_data']['asset_id'] = str(get_test_uuid())
        resp = await RestApiClient.call(
            API, method=HttpMethod.POST, headers=ssl_headers, data=claim_data,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data['request_id'])
        self.assertEqual(data['status'], 'accepted')
        self.assertIsNotNone(data['signature'])
        self.assertIsNotNone(data['signature_timestamp'])
        self.assertIsNotNone(data['issuer_id'])
        self.assertIsNotNone(data['issuer_type'])
        self.assertIsNotNone(data['cert_fingerprint'])
        self.assertIsNotNone(data['cert_expiration'])

        claim_file = server.get_claim_filepath(
            ClaimStatus.ACCEPTED, claim_data['claim_data']['asset_id']
        )
        self.assertTrue(os.path.exists(claim_file))

        #
        # Test with JWT and whitelisted member
        #
        # Make sure asset_id is unique
        claim_data['claim_data']['asset_id'] = str(get_test_uuid())
        resp = await RestApiClient.call(
            API, method=HttpMethod.POST, headers=jwt_headers, data=claim_data,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data['request_id'])
        self.assertEqual(data['status'], 'accepted')
        self.assertIsNotNone(data['signature'])
        self.assertIsNotNone(data['signature_timestamp'])
        self.assertIsNotNone(data['issuer_id'])
        self.assertIsNotNone(data['issuer_type'])
        self.assertIsNotNone(data['cert_fingerprint'])
        self.assertIsNotNone(data['cert_expiration'])

        claim_file = server.get_claim_filepath(
            ClaimStatus.ACCEPTED, claim_data['claim_data']['asset_id']
        )
        self.assertTrue(os.path.exists(claim_file))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
