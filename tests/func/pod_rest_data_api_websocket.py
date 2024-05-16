#!/usr/bin/env python3

'''
Test the POD REST Data APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

These tests need a local webserver running on port 8000 as the
pynng does not allow you to spawn a server from the test code.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

import os
import sys
import socket
import unittest

from datetime import datetime
from datetime import timezone

import orjson

from anyio import TASK_STATUS_IGNORED
from anyio import create_task_group
from anyio import sleep
from anyio.abc import TaskStatus

from byoda.datamodel.network import Network
from byoda.datamodel.member import Member
from byoda.datamodel.account import Account

from byoda.datatypes import DataRequestType
from byoda.datatypes import IdType
from byoda.datatypes import DataFilterType

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.data_wsapi_client import DataWsApiClient
from byoda.util.api_client.api_client import ApiClient

from byoda.util.logger import Logger

from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import get_account_id

from tests.lib.auth import get_member_auth_header
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.util import get_test_uuid
from tests.lib.util import call_data_api


TEST_DIR = '/tmp/byoda-tests/podserver'

SLEEP_INTERVAL: int = 1

ASSET: dict[str, dict[str, object]] = {
    'data': {
        'created_timestamp': str(datetime.now(tz=timezone.utc).isoformat()),
        'asset_id': str(get_test_uuid()),
        'asset_type': 'video',
        'video_chapters': [
            {
                'chapter_id': get_test_uuid(),
                'start': 0, 'end': 10, 'title': 'chapter 1'
            },
            {
                'chapter_id': get_test_uuid(),
                'start': 11, 'end': 20, 'title': 'chapter 2'
            },
        ],
    }
}


async def listen_for_updates(
        test, member: Member, class_name: str, auth_header: dict[str, str],
        network_name: str, data_filter: DataFilterType, test_counter: int,
        *,
        task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
    '''
    Listen for updates

    :param test: instance of async unittest
    :param member: our membership
    :param class_name:
    :param auth_header:
    :param network_name:
    :param task_status: task status parameter added by taskgroup.start()
    :returns: (none)
    :raises:
    '''

    task_status.started()

    async for message in DataWsApiClient.call(
            member.service_id, class_name, DataRequestType.UPDATES,
            headers=auth_header, network=network_name, data_filter=data_filter,
            member_id=member.member_id, internal=True, timeout=1800):

        data = orjson.loads(message)
        if test_counter in (1, 2, 3):
            test.assertEqual(data['origin_id'], str(member.member_id))
            test.assertEqual(data['origin_id_type'], IdType.MEMBER.value)
            test.assertEqual(data['origin_class_name'], None)
            test.assertEqual(
                data['node']['asset_id'], str(ASSET['data']['asset_id'])
            )

        if test_counter == 4:
            test.assertEqual(data['origin_id'], str(member.member_id))
            test.assertEqual(data['origin_id_type'], IdType.MEMBER.value)
            test.assertEqual(data['origin_class_name'], None)
            # In this test, we only get the data specified in the filter back,
            # not the other fields of the data object
            test.assertEqual(
                data['node']['asset_id'], str(ASSET['data']['asset_id'])
            )
            test.assertIsNone(data['node'].get('locale'))
            test.assertIsNotNone(data['filter'])

        if test_counter == 5:
            test.assertIsNotNone(data.get('filter'))

        return


async def call_api(test, member: Member, class_name: str,
                   action: DataRequestType, data, headers,
                   data_filter: DataFilterType = None
                   ) -> dict[str, object] | int | None:
    '''

    '''
    resp: dict[str, object] | int | None = await call_data_api(
        member.service_id, class_name, action, data=data,
        member=member, data_filter=data_filter,
        auth_header=headers, test=test, internal=True
    )
    return resp


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR, hash_password=False)
        network_data: dict[str, str] = await setup_network(
            delete_tmp_dir=False
        )

        # This test case requires pub/sub to be enabled to/from
        # locally running podserver using port 8000 so we do not
        # set config.test_case
        config.test_case = 'TEST_CLIENT'

        server: PodServer = config.server

        network_data['account_id'] = get_account_id(network_data)

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account: Account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

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

    async def test_websocket_append(self) -> None:
        account: Account = config.server.account
        network: Network = account.network
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        auth_header: str = await get_member_auth_header(service_id, test=self)

        class_name: str = 'network_assets'
        test: int
        data_filter: DataFilterType | None
        global ASSET

        # Test 1: standard append without data filter
        async with create_task_group() as tg:
            test = 1
            asset_id = str(get_test_uuid())
            ASSET['data']['asset_id'] = asset_id
            data_filter = None
            await tg.start(
                listen_for_updates, self, member, class_name, auth_header,
                network.name, data_filter, test
            )
            await sleep(SLEEP_INTERVAL)
            tg.start_soon(
                call_api, self, member, class_name,
                DataRequestType.APPEND, ASSET, auth_header
            )

        # Test 2: append  with 'ne' filter for updates for non-existant
        # asset_id
        async with create_task_group() as tg:
            test = 2
            asset_id = str(get_test_uuid())
            ASSET['data']['asset_id'] = asset_id
            data_filter = {
                'asset_id': {'ne': get_test_uuid()}
            }
            await tg.start(
                listen_for_updates, self, member, class_name, auth_header,
                network.name, data_filter, test
            )
            await sleep(SLEEP_INTERVAL)
            tg.start_soon(
                call_api, self, member, class_name,
                DataRequestType.APPEND, ASSET, auth_header
            )

        # Test 3: append with 'eq' filter for updates matching the asset_id
        async with create_task_group() as tg:
            test = 3
            asset_id = str(get_test_uuid())
            ASSET['data']['asset_id'] = asset_id
            data_filter = {
                'asset_id': {'eq': asset_id}
            }
            await tg.start(
                listen_for_updates, self, member, class_name, auth_header,
                network.name, data_filter, test
            )
            await sleep(SLEEP_INTERVAL)
            tg.start_soon(
                call_api, self, member, class_name,
                DataRequestType.APPEND, ASSET, auth_header
            )

        # Test 4: update the asset
        async with create_task_group() as tg:
            test = 4
            ASSET['data']['asset_type'] = 'post'
            data_filter = {
                'asset_id': {'eq': asset_id}
            }
            await tg.start(
                listen_for_updates, self, member, class_name, auth_header,
                network.name, None, test
            )
            await sleep(SLEEP_INTERVAL)
            tg.start_soon(
                call_api, self, member, class_name,
                DataRequestType.UPDATE, ASSET, auth_header, data_filter
            )

        # Test 5: mutate the asset
        async with create_task_group() as tg:
            test = 5
            data_filter = {
                'asset_id': {'eq': asset_id}
            }
            await tg.start(
                listen_for_updates, self, member, class_name, auth_header,
                network.name, None, test
            )
            await sleep(SLEEP_INTERVAL)
            tg.start_soon(
                call_api, self, member, class_name,
                DataRequestType.DELETE, None, auth_header, data_filter
            )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result: int = sock.connect_ex(('127.0.0.1', 8000))
    if result != 0:
        raise RuntimeError(
            'These websocket tests need a running pod server on port 8000'
        )

    unittest.main()
