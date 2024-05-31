#!/usr/bin/env python3

'''
Test the CDN content keys APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license
'''

import os
import sys
import yaml
import shutil
import unittest

from uuid import UUID
from typing import TypeVar
from datetime import datetime
from datetime import timedelta
from datetime import UTC


from fastapi import FastAPI

from byoda.datamodel.network import Network
from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.app_server import AppServer

from byoda.datatypes import CloudType
from byoda.datatypes import AppType
from byoda.datatypes import StorageType

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.api_client import HttpMethod
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda import config

from byoda.util.fastapi import setup_api

from tests.lib.defines import COLLATERAL_DIR
from tests.lib.defines import BYOTUBE_SERVICE_ID
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.util import get_test_uuid

from tests.lib.setup import mock_environment_vars

from appserver.routers import cdn as CdnRouter
from appserver.routers import status as StatusRouter

Member = TypeVar('Member')

CONFIG_FILE: str = 'tests/collateral/local/config-cdn-keys.yml'
TEST_DIR: str = '/tmp/byoda-test/cdn_keys_api'
TEST_PORT: int = 8000
BASE_URL: str = f'http://localhost:{TEST_PORT}/api/v1'

TEST_APP_ID: str = '05cbb871-ee50-4ba5-8dda-4879142fb67e'

_LOGGER: Logger

APP: FastAPI | None = None


class TestApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR)

        config.test_case = True
        config.debug = True
        config.tls_cert_file = '/tmp/cert.pem'
        with open(CONFIG_FILE) as file_desc:
            TestApis.APP_CONFIG: dict[str, dict[str, any]] = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        app_config: dict[str, dict[str, any]] = TestApis.APP_CONFIG
        app_config['appserver']['root_dir'] = TEST_DIR
        app_config['cdnserver']['keys_dir'] = f'{TEST_DIR}/cdn_keys'
        app_config['cdnserver']['origins_dir'] = f'{TEST_DIR}/cdn_origins'
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        paths: dict[str, str] = {
            'key': '/private/network-byoda.net/service-4294929430/apps/',
            'pem': '/network-byoda.net/service-4294929430/apps/'
        }
        os.makedirs(f'{TEST_DIR}{paths["key"]}', exist_ok=True)
        os.makedirs(f'{TEST_DIR}{paths["pem"]}', exist_ok=True)
        files: tuple[str, str, str, str] = (
            f'app-{TEST_APP_ID}-cert.pem', f'app-data-{TEST_APP_ID}-cert.pem',
            f'app-{TEST_APP_ID}.key', f'app-data-{TEST_APP_ID}.key'
        )
        for file in files:
            file_type: str = file[-3:]
            filepath: str = paths[file_type] + file
            shutil.copyfile(
                f'{COLLATERAL_DIR}/local/{file}',
                f'{TEST_DIR}{filepath}'
            )

        network = Network(
            app_config['appserver'], app_config['application']
        )

        server = AppServer(
            AppType.CDN, app_config['appserver']['app_id'], network,
            app_config, [StatusRouter, CdnRouter]
        )
        config.server = server

        config.server.paths = network.paths

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType.LOCAL,
            private_bucket='byoda',
            restricted_bucket='byoda',
            public_bucket='byoda',
            root_dir=app_config['appserver']['root_dir']
        )

        await network.load_network_secrets()
        await server.load_secrets(
            password=app_config['appserver']['private_key_password']
        )

        if not os.environ.get('SERVER_NAME') and config.server.network.name:
            os.environ['SERVER_NAME'] = config.server.network.name

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server)

        global APP
        APP = setup_api(
            'Byoda CDN content keys server', 'server for content keys APIs',
            'v0.0.1', [StatusRouter, CdnRouter], lifespan=None,
            trace_server=config.trace_server
        )

    @classmethod
    async def asyncTearDown(cls) -> None:
        await ApiClient.close_all()

    async def test_cdn_content_keys_post_jwt(self) -> None:
        test_dir: str = f'/{TEST_DIR}/cdn_keys'
        try:
            shutil.rmtree(test_dir)
        except FileNotFoundError:
            pass
        API: str = BASE_URL + '/cdn/content_keys'

        network_name: str = TestApis.APP_CONFIG['application']['network']

        member_id: UUID = get_test_uuid()
        ssl_headers: dict[str, str] = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={member_id}.members-{ADDRESSBOOK_SERVICE_ID}.{network_name}',      # noqa: E501
            'X-Client-SSL-Issuing-CA':
                (
                    'CN=members-ca.members-ca-'
                    f'{ADDRESSBOOK_SERVICE_ID}.{network_name}'
                )
        }

        data: list[dict[str, str | int]] = [
            {
                'key_id': 1,
                'key': 'cdnapi.py-test_cdn_content_keys_api-1',
                'not_before': datetime.now(tz=UTC).isoformat(),
                'not_after':
                    (datetime.now(tz=UTC) + timedelta(days=1)).isoformat(),
            }
        ]
        #
        # Test with SSL headers
        #
        resp: HttpResponse = await RestApiClient.call(
            API, method=HttpMethod.POST, headers=ssl_headers, data=data,
            timeout=600, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        filepath: str = f'/{TEST_DIR}/cdn_keys/{member_id}-keys.json'
        self.assertTrue(os.path.exists(filepath))

    async def test_cdn_origins_post_jwt(self) -> None:
        test_dir: str = f'/{TEST_DIR}/cdn_origins/'
        try:
            shutil.rmtree(test_dir)
        except FileNotFoundError:
            pass

        API: str = BASE_URL + '/cdn/origins'

        network_name: str = TestApis.APP_CONFIG['application']['network']

        account_id: UUID = get_test_uuid()
        ssl_headers: dict[str, str] = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject':
                f'CN={account_id}.accounts.{network_name}',
            'X-Client-SSL-Issuing-CA': 'CN=accounts-ca.accounts-ca.byoda.net'
        }

        member_ids: list[UUID] = [get_test_uuid(), get_test_uuid()]
        data: dict[str, int | dict[str, str | UUID | StorageType]] = {
            'service_id': BYOTUBE_SERVICE_ID,
            'member_id': member_ids[0],
            'buckets': {
                StorageType.RESTRICTED.value:
                    f'{account_id}-restricted-123456',
                StorageType.PUBLIC.value: f'{account_id}-public',
            }
        }
        resp: HttpResponse = await RestApiClient.call(
            API, method=HttpMethod.POST, headers=ssl_headers, data=data,
            timeout=600, app=APP
        )
        self.assertEqual(resp.status_code, 201)
        filepath: str = \
            f'{test_dir}/{BYOTUBE_SERVICE_ID}-{account_id}-origins.json'
        self.assertTrue(os.path.exists(filepath))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
