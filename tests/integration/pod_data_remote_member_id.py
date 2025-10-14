#!/usr/bin/env python3

'''
Test the POD Data APIs with depth=1 and remote_member_id != None

These tests use the BYO.Tube service and the 'Dathes' POD

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license
'''

import os
import sys

import unittest

from uuid import UUID
from logging import Logger

from datetime import UTC
from datetime import datetime

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import DataRequestType

from byoda.util.api_client.api_client import ApiClient

from byoda.servers.pod_server import PodServer

from byoda.util.fastapi import setup_api

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.auth import get_member_auth_header
from tests.lib.auth import get_pod_jwt
from tests.lib.util import get_test_uuid
from tests.lib.util import call_data_api

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars

from tests.lib.defines import BYOTUBE_SERVICE_ID
from tests.lib.defines import DATHES_POD_MEMBER_ID
from tests.lib.defines import BASE_URL

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

    async def test_pod_rest_data_api_remote_append(self) -> None:
        account: Account = config.server.account
        service_id: int = BYOTUBE_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        member_id: UUID = member.member_id

        member_auth_header: dict[str, str] = await get_member_auth_header(
            service_id, APP, self
        )

        # First we add a comment to our own pod
        comment: dict[str, str | UUID] = {
            'message_id': get_test_uuid(),
            'contents': 'This is a test comment',
            'sender_id': member_id,
            'created_timestamp': datetime.now(tz=UTC).isoformat(),
        }

        result: dict[str, object] | int | None = await call_data_api(
            BYOTUBE_SERVICE_ID, 'messages', action=DataRequestType.APPEND,
            data={'data': comment}, auth_header=member_auth_header, app=APP,
            member=member
        )

        # Let's read back that comment from our own pod
        self.assertEqual(result, 1)
        data: dict[str, object] | int | None = await call_data_api(
            BYOTUBE_SERVICE_ID, 'messages', action=DataRequestType.QUERY,
            auth_header=member_auth_header, app=APP, member=member
        )
        self.assertIsNotNone(data)
        self.assertEqual(data['total_count'], 1)
        edge = data['edges'][0]
        self.assertEqual(edge['origin'], str(member_id))
        node = edge['node']
        self.assertEqual(node['sender_id'], str(member_id))

        # Add comment to remote pod 'dathes
        comment = {
            'message_id': get_test_uuid(),
            'contents': 'This is a proxied test comment',
            'sender_id': member_id,
            'created_timestamp': datetime.now(tz=UTC).isoformat(),
        }
        result: dict[str, object] | int | None = await call_data_api(
            BYOTUBE_SERVICE_ID, 'messages', action=DataRequestType.APPEND,
            data={'data': comment}, auth_header=member_auth_header, app=APP,
            member=member, depth=1, remote_member_id=DATHES_POD_MEMBER_ID
        )
        self.assertEqual(result, 1)

        # Get the comments from the remote pod, should not include
        # comments from our own pod
        result: dict[str, object] | int | None = await call_data_api(
            BYOTUBE_SERVICE_ID, 'messages', action=DataRequestType.QUERY,
            auth_header=member_auth_header, member=member, app=APP,
            depth=1, remote_member_id=DATHES_POD_MEMBER_ID
        )
        self.assertTrue(isinstance(result, dict))
        self.assertGreaterEqual(result['total_count'], 1)
        edges: list[dict[str, any]] = result['edges']

        origins: set[str] = set([edge['node']['sender_id'] for edge in edges])
        self.assertTrue(str(member_id) in origins)

        dathes_auth_header: str
        pod_fqdn: str
        dathes_auth_header, pod_fqdn = await get_pod_jwt(
            account, 'dathes', TEST_DIR, DATHES_POD_MEMBER_ID,
            BYOTUBE_SERVICE_ID
        )

        self.assertIsNotNone(dathes_auth_header)
        self.assertIsNotNone(pod_fqdn)

        dathes_member: Member = Member(
            BYOTUBE_SERVICE_ID, account=account, member_id=DATHES_POD_MEMBER_ID
        )
        result: dict[str, object] | int | None = await call_data_api(
            BYOTUBE_SERVICE_ID, 'messages', action=DataRequestType.DELETE,
            auth_header=dathes_auth_header, member=dathes_member,
            data_filter={'sender_id': {'eq': str(member_id)}},
            internal=False
        )
        self.assertEqual(result, 1)

    async def test_pod_rest_data_api_remote_member_query(self) -> None:
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
        self.assertNotIn(member_id, origins)

        await call_data_api(
            BYOTUBE_SERVICE_ID, 'public_assets', action=DataRequestType.APPEND,
            data={'data': asset}, auth_header=member_auth_header, app=APP,
            member=member
        )


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
