#!/usr/bin/env python3

'''
Test the CDN content_keys API

These tests are run against the production CDN API server
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license
'''

import os
import sys
import unittest

from datetime import UTC
from datetime import datetime
from datetime import timedelta

import httpx

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.network import Network

from byoda.datatypes import CDN_KEYS_API

from byoda.secrets.member_secret import MemberSecret

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from byoda import config
from byoda.util.paths import Paths

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars

from tests.lib.defines import BYOTUBE_SERVICE_ID
from tests.lib.defines import BYOTUBE_VERSION

CDN_API_HOST: str = '928ef3d7-f4fd-4b41-b6c8-2bc4a201b2e8.apps-16384.byoda.net'
TEST_DIR: str = '/tmp/byoda-tests/pod-rest-apis'


class TestPodApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR)
        network_data: dict[str, str] = await setup_network(delete_tmp_dir=True)

        config.test_case = 'TEST_CLIENT'
        config.disable_pubsub = True

        server: PodServer = config.server

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account: Account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False,
            service_id=BYOTUBE_SERVICE_ID, version=BYOTUBE_VERSION
        )
        server.account = account
        member: Member = await account.get_membership(BYOTUBE_SERVICE_ID)
        key_password: str = network_data['private_key_password']
        member.tls_secret.password = key_password

    async def test_cdn_content_keys_api(self) -> None:
        server: PodServer = config.server
        account: Account = server.account
        member: Member = await account.get_membership(BYOTUBE_SERVICE_ID)
        tls_secret: MemberSecret = member.tls_secret
        data: list[dict[str, str | int]] = [
            {
                'key_id': 1,
                'content_token': 'cdnapi.py-test_cdn_content_keys_api-1',
                'not_before': datetime.now(tz=UTC).isoformat(),
                'not_after':
                    (datetime.now(tz=UTC) + timedelta(days=1)).isoformat(),
            }
        ]

        network: Network = server.network
        paths: Paths = network.paths
        root_ca_file: str = \
            paths.root_directory + '/' + paths.get(
                Paths.NETWORK_ROOT_CA_CERT_FILE
            )
        tls_cert_file: str = paths.root_directory + '/' + tls_secret.cert_file
        tls_key_file: str = \
            paths.root_directory + '/' + tls_secret.private_key_file
        resp: httpx.Response = httpx.post(
            f'https://{CDN_API_HOST}{CDN_KEYS_API}',
            json=data,
            cert=(
                tls_cert_file, tls_key_file, tls_secret.password
            ),
            verify=root_ca_file,
        )
        self.assertEqual(resp.status_code, 200)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
