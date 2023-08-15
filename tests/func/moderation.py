#!/usr/bin/env python3

'''
Test the Directory APIs

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
import requests

from multiprocessing import Process
import uvicorn

from byoda.datamodel.network import Network

from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.app_server import AppServer

from byoda.datatypes import CloudType
from byoda.datatypes import ClaimStatus

from byoda.util.logger import Logger
from byoda.util.api_client.api_client import ApiClient

from byoda import config

from byoda.util.fastapi import setup_api

from tests.lib.defines import COLLATERAL_DIR
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.util import get_test_uuid

from modserver.routers import moderate as ModerateRouter
from modserver.routers import status as StatusRouter


CONFIG_FILE = 'tests/collateral/local/config-mod.yml'
TEST_DIR = '/tmp/byoda-tests/mod_apis'
TEST_PORT = 8000
BASE_URL = f'http://localhost:{TEST_PORT}/api/v1'

_LOGGER = None


class TestApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
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
            'app-05cbb871-ee50-4ba5-8dda-4879142fb67e-cert.pem',
            'app-data-05cbb871-ee50-4ba5-8dda-4879142fb67e-cert.pem',
            'app-05cbb871-ee50-4ba5-8dda-4879142fb67e.key',
            'app-data-05cbb871-ee50-4ba5-8dda-4879142fb67e.key'
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
            app = setup_api(
                'Byoda test dirserver', 'server for testing directory APIs',
                'v0.0.1', [StatusRouter, ModerateRouter], lifespan=None
            )
            TestApis.PROCESS = Process(
                target=uvicorn.run,
                args=(app,),
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

    def test_moderation_asset_post(self):
        API = BASE_URL + '/moderate/asset'
        server: AppServer = config.server

        member_id = get_test_uuid()
        network_name = TestApis.APP_CONFIG['application']['network']
        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={member_id}.members-{ADDRESSBOOK_SERVICE_ID}.{network_name}',      # noqa: E501
            'X-Client-SSL-Issuing-CA':
                (
                    'CN=members-ca.members-ca-'
                    f'{ADDRESSBOOK_SERVICE_ID}.{network_name}'
                )
        }

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
                'publisher': 'YouTube',
                'publisher_asset_id': '5Y9L5NBINV4',
                'title': 'Big Buck Bunny',
                'contents': '',
                'annotations': [],
            }
        }
        response = requests.post(API, headers=headers, json=claim_data)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'pending')
        self.assertIsNone(data['signature'])
        self.assertIsNotNone(data['request_id'])
        request_file = server.get_claim_filepath(
            ClaimStatus.PENDING, data['request_id']
        )
        self.assertTrue(os.path.exists(request_file))

        claim_data['claim_data']['asset_id'] = str(get_test_uuid())
        whitelist_file = f'{server.whitelist_dir}/{member_id}'
        with open(whitelist_file, 'w') as file_desc:
            file_desc.write('')

        response = requests.post(API, headers=headers, json=claim_data)
        self.assertEqual(response.status_code, 200)
        data = response.json()
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
