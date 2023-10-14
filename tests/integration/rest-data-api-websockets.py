#!/usr/bin/env python3

import os
import sys
import unittest

from uuid import UUID
from ssl import SSLContext
from datetime import datetime
from datetime import timezone

import orjson
import websockets

from fastapi import FastAPI

from websockets.legacy.client import WebSocketClientProtocol

from anyio.abc import TaskStatus
from anyio import create_task_group
from anyio import TASK_STATUS_IGNORED

from byoda.datamodel.account import Account

from byoda.models.data_api_models import AnyScalarType

from byoda.datatypes import DataRequestType

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.data_wsapi_client import DataWsApiClient
from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter


from tests.lib.setup import setup_network
from tests.lib.setup import get_account_id
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars

from tests.lib.util import get_test_uuid
from tests.lib.auth import get_member_auth_header
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from podserver.codegen.pydantic_service_4294929430_1 import asset
TEST_DIR: str = '/tmp/byoda-tests/podserver'


class TestRestDataApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)
        network_data['account_id'] = get_account_id(network_data)

        config.test_case = 'TEST_CLIENT'

        server: PodServer = config.server

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account: Account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
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
            await member.create_query_cache()
            await member.create_counter_cache()
            await member.enable_data_apis(APP, server.data_store)

    @classmethod
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_websocket_updates(self):
        service_id: int = ADDRESSBOOK_SERVICE_ID
        class_name: str = 'network_assets'

        member_auth_header: dict[str, str] = await get_member_auth_header(
            service_id, APP
        )

        ws_updates_uri: str
        ssl_context: SSLContext
        ws_updates_uri, ssl_context = await DataWsApiClient.get_url(
            service_id, class_name, DataRequestType.UPDATES, None, False,
            None, None, None, True
        )

        async with websockets.connect(
                ws_updates_uri, ping_timeout=600, ping_interval=300,
                extra_headers=member_auth_header) as webs:
            async with create_task_group() as tg:
                await tg.start(send_api_request, webs)
                await tg.start(listen_api, self, webs, DataRequestType.UPDATES)
                tg.start_soon(
                    append_data, member_auth_header, service_id, class_name
                )

    async def test_websocket_counter(self):
        service_id: int = ADDRESSBOOK_SERVICE_ID
        class_name: str = 'network_assets'

        member_auth_header: dict[str, str] = await get_member_auth_header(
            service_id, APP
        )

        ws_updates_uri: str
        ssl_context: SSLContext
        ws_updates_uri, ssl_context = await DataWsApiClient.get_url(
            service_id, class_name, DataRequestType.COUNTER, None, False,
            None, None, None, True
        )
        async with websockets.connect(
                ws_updates_uri, ping_timeout=600, ping_interval=300,
                extra_headers=member_auth_header) as webs:
            async with create_task_group() as tg:
                await tg.start(send_api_request, webs)
                await tg.start(listen_api, self, webs, DataRequestType.COUNTER)
                tg.start_soon(
                    append_data, member_auth_header, service_id, class_name
                )

    async def test_data_wsapi_counter(self):
        server: PodServer = config.server
        account: Account = server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        class_name: str = 'network_assets'
        action: DataRequestType = DataRequestType.COUNTER
        member = await account.get_membership(service_id)

        member_auth_header: dict[str, str] = await get_member_auth_header(
            service_id, APP
        )

        async with create_task_group() as tg:
            await tg.start(
                use_data_wsapi_client, self, service_id, class_name, action,
                member_auth_header, member.member_id
            )
            tg.start_soon(
                append_data, member_auth_header, service_id, class_name
            )

    async def test_data_wsapi_updates(self):
        server: PodServer = config.server
        account: Account = server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        class_name: str = 'network_assets'
        action: DataRequestType = DataRequestType.UPDATES
        member = await account.get_membership(service_id)

        member_auth_header: dict[str, str] = await get_member_auth_header(
            service_id, APP
        )

        async with create_task_group() as tg:
            await tg.start(
                use_data_wsapi_client, self, service_id, class_name, action,
                member_auth_header, member.member_id
            )
            tg.start_soon(
                append_data, member_auth_header, service_id, class_name
            )

    async def test_websocket_no_subscribe_right(self):
        server: PodServer = config.server
        account: Account = server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        class_name: str = 'datalogs'
        action: DataRequestType = DataRequestType.UPDATES
        member = await account.get_membership(service_id)

        member_auth_header: dict[str, str] = await get_member_auth_header(
            service_id, APP
        )

        with self.assertRaises(websockets.exceptions.ConnectionClosedError):
            async with create_task_group() as tg:
                await tg.start(
                    use_data_wsapi_client, self, service_id, class_name,
                    action, member_auth_header, member.member_id
                )
                tg.start_soon(
                    append_datalogs, member_auth_header, service_id
                )

        # Dummy test
        self.assertEqual(service_id, ADDRESSBOOK_SERVICE_ID)


async def use_data_wsapi_client(test, service_id: int, class_name: str,
                                action: DataRequestType,
                                headers: dict[str, str],
                                member_id: UUID,
                                task_status: TaskStatus[None] =
                                TASK_STATUS_IGNORED):
    task_status.started()
    async for response in DataWsApiClient.call(
            service_id, class_name, action, member_id=member_id,
            headers=headers, internal=True):
        if action == DataRequestType.UPDATES:
            data = orjson.loads(response)
            test.assertIsNotNone(data['origin'])
            test.assertIsNotNone(data['cursor'])
            test.assertIsNotNone(data['query_id'])

            node = data['node']
            test.assertIsNotNone(node)
            model = asset.model_validate(node)
            test.assertEqual(model.asset_type, 'post')
        else:
            data = orjson.loads(response)
            test.assertIsNotNone(data['origin'])
            test.assertIsNotNone(data['cursor'])
            test.assertIsNotNone(data['query_id'])
            test.assertGreater(data['counter'], 0)

        return


async def send_api_request(
        websocket: WebSocketClientProtocol,
        task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
    _LOGGER.info('Sending message')
    model = {
        'query_id': get_test_uuid(),
        'depth': 0,
    }
    await websocket.send(orjson.dumps(model))
    task_status.started()


async def listen_api(
        test, websocket: WebSocketClientProtocol,
        request_type: DataRequestType,
        task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
    task_status.started()
    response = await websocket.recv()
    if request_type == DataRequestType.UPDATES:
        data = orjson.loads(response)
        test.assertIsNotNone(data['origin'])
        test.assertIsNotNone(data['cursor'])
        test.assertIsNotNone(data['query_id'])

        node = data['node']
        test.assertIsNotNone(node)
        model = asset.model_validate(node)
        test.assertEqual(model.asset_type, 'post')
    else:
        data = orjson.loads(response)
        test.assertIsNotNone(data['origin'])
        test.assertIsNotNone(data['cursor'])
        test.assertIsNotNone(data['query_id'])
        test.assertGreater(data['counter'], 0)


async def append_data(member_auth_header: dict[str, str], service_id: int,
                      class_name: str, app: FastAPI = None) -> HttpResponse:
    count: int = 0

    vars = {
        'created_timestamp': str(
            datetime.now(tz=timezone.utc).isoformat()
        ),
        'asset_type': 'post',
        'asset_id': str(get_test_uuid()),
        'creator': f'test account #{count}',
        'title': f'test asset-{count}',
        'subject': 'just a test asset',
        'contents': 'some utf-8 markdown string',
        'keywords': ["just", "testing"],
        'video_thumbnails': [
            {
                'thumbnail_id': get_test_uuid(),
                'url': 'https://dummy-1.com',
                'width': 640,
                'height': 480
            },
            {
                'thumbnail_id': get_test_uuid(),
                'url': 'https://dummy-2.com',
                'width': 320,
                'height': 240
            }
        ],
        'video_chapters': [
            {
                'chapter_id': get_test_uuid(),
                'start': 0, 'end': 10, 'title': 'chapter 1'
            },
            {
                'chapter_id': get_test_uuid(),
                'start': 11, 'end': 20, 'title': 'chapter 2'
            },
            {
                'chapter_id': get_test_uuid(),
                'start': 21, 'end': 30, 'title': 'chapter 3'
            },
        ]
    }

    data: {str, dict[str, AnyScalarType]} = {
        'query_id': get_test_uuid(),
        'data': vars
    }

    resp: HttpResponse = await DataApiClient.call(
        service_id, class_name, DataRequestType.APPEND,
        headers=member_auth_header, data=data,
        timeout=300, internal=True
    )

    if resp.status_code != 200:
        raise RuntimeError('Failed to append to network_assets')

    return resp


async def append_datalogs(member_auth_header: dict[str, str], service_id: int
                          ) -> HttpResponse:
    vars = {
        'created_timestamp': str(
            datetime.now(tz=timezone.utc).isoformat()
        ),
        'remote_addr': '10.10.10.10',
        'operation': 'SUBSCRIBE',
        'object': 'network_assets'
    }

    data: {str, dict[str, AnyScalarType]} = {
        'query_id': get_test_uuid(),
        'data': vars
    }

    resp: HttpResponse = await DataApiClient.call(
        service_id, 'datalogs', DataRequestType.APPEND,
        headers=member_auth_header, data=data,
        timeout=300, internal=True
    )

    if resp.status_code != 200:
        raise RuntimeError('Failed to append to network_assets')

    return resp

if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
