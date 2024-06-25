#!/usr/bin/env python3

'''
Test the POD Data APIs with depth=1 and remote_member_id != None

These tests use the BYO.Tube service and the 'Dathes' POD

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

import os
import sys
import unittest

from uuid import UUID
from datetime import UTC
from datetime import datetime

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.servers.pod_server import PodServer

from byoda.util.fastapi import setup_api

from byoda.util.logger import Logger

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.auth import get_member_auth_header

from tests.lib.util import get_test_uuid
from tests.lib.util import call_data_api

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars

from tests.lib.defines import BASE_URL
from tests.lib.defines import BYOTUBE_SERVICE_ID
from tests.lib.defines import DATHES_POD_MEMBER_ID
from tests.lib.defines import DATHES_POD_MEMBER_FQDN

# Settings must match config.yml used by directory server
NETWORK: str = config.DEFAULT_NETWORK

# This must match the test directory in tests/lib/testserver.p
TEST_DIR: str = '/tmp/byoda-tests/pod-rest-data-apis'

TIMEOUT: int = 300

APP: FastAPI | None = None


class TestRestDataApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR)
        network_data: dict[str, str] = await setup_network(delete_tmp_dir=True)

        config.test_case = 'TEST_CLIENT'
        config.disable_pubsub = True

        server: PodServer = config.server

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account: Account = await setup_account(
            network_data, test_dir=TEST_DIR, service_id=BYOTUBE_SERVICE_ID,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        global APP
        APP = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [
                AccountRouter, MemberRouter, AuthTokenRouter,
                AccountDataRouter
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        for member in account.memberships.values():
            await member.enable_data_apis(
                APP, server.data_store, server.cache_store
            )

    @classmethod
    async def asyncTearDown(self) -> None:
        await ApiClient.close_all()

    async def test_pod_rest_data_api_recursive_append(self) -> None:
        account: Account = config.server.account
        service_id: int = BYOTUBE_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        member_id: UUID = member.member_id

        member_auth_header: dict[str, str] = await get_member_auth_header(
            service_id, APP, self
        )

        # asset_url: str = 'http://localhost:8000/api/v1/service/asset'

        asset: dict[str, str | UUID] = {
            'asset_id': get_test_uuid(),
            'asset_type': 'video',
            'title': 'Test video',
            'created_timestamp': datetime.now(tz=UTC).isoformat(),
        }
        await call_data_api(
            BYOTUBE_SERVICE_ID, 'public_assets', action=DataRequestType.APPEND,
            data={'data': asset}, auth_header=member_auth_header, app=APP,
            member=member
        )

        result = await call_data_api(
            BYOTUBE_SERVICE_ID, 'public_assets', action=DataRequestType.QUERY,
            depth=0, auth_header=member_auth_header, app=APP, member=member
        )
        self.assertEqual(result['total_count'], 1)

        result = await call_data_api(
            BYOTUBE_SERVICE_ID, 'public_assets', action=DataRequestType.QUERY,
            depth=1, auth_header=member_auth_header, app=APP, member=member
        )
        # We do not have network_links so we only get back our own asset
        self.assertEqual(result['total_count'], 1)

        # Now we specify remote_member_id. We should get back only the
        # assets of the remote pod, not our own.
        result: dict[str, object] = await call_data_api(
            BYOTUBE_SERVICE_ID, 'public_assets', action=DataRequestType.QUERY,
            depth=1, auth_header=member_auth_header, app=APP, member=member,
            remote_member_id=DATHES_POD_MEMBER_ID
        )
        self.assertIsNotNone(result)
        origins: set[str] = set([edge['origin'] for edge in result['edges']])
        self.assertFalse(member_id in origins)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
