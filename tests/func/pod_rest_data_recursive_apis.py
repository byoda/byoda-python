#!/usr/bin/env python3

'''
Test the POD REST and Data APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

# flake8: noqa: E266

import os
import sys
import unittest

from uuid import UUID
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType
from byoda.datatypes import MARKER_NETWORK_LINKS
from byoda.datatypes import AnyScalarType
from byoda.datatypes import DataFilterType

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda.exceptions import ByodaRuntimeError

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.util import get_test_uuid
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID


from tests.lib.auth import get_azure_pod_jwt

# Settings must match config.yml used by directory server
NETWORK: str = config.DEFAULT_NETWORK

# This must match the test directory in tests/lib/testserver.p
TEST_DIR: str = '/tmp/byoda-tests/pod-rest-data-apis'

TIMEOUT: int = 300

APP: FastAPI | None = None

ALL_DATA: list[dict[str, AnyScalarType]] = []


class TestRestDataApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR)
        network_data: dict[str, str] = await setup_network(delete_tmp_dir=True)

        config.test_case = 'TEST_CLIENT'
        config.disable_pubsub = True

        server: PodServer = config.server

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account: Account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        config.trace_server: str = os.environ.get(
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
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        member_id: UUID = member.member_id

        member_auth_header: dict[str, str] = await get_member_auth_header(
            self, member.member_id
        )

        class_name: str = 'network_links_inbound'
        data: dict[str, dict[str, object]] = {
            'data': {
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                ),
                'member_id': member_id,
                'relation': 'friend',
            }
        }

        resp: HttpResponse = await DataApiClient.call(
            service_id, class_name, DataRequestType.APPEND,
            data=data, remote_member_id=AZURE_POD_MEMBER_ID, depth=1,
            headers=member_auth_header,
            member_id=AZURE_POD_MEMBER_ID, app=APP, timeout=TIMEOUT,
        )
        append_count = resp.json()
        self.assertEqual(append_count, 1)

    async def test_pod_rest_data_api_recursive_query(self) -> None:
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        member_id: UUID = member.member_id

        member_auth_header: dict[str, str] = await get_member_auth_header(
            self, member.member_id
        )

        class_name: str = 'network_assets'

        # First non-recursive query, without data populated
        local_data = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=0,
            auth_header=member_auth_header
        )
        self.assertEqual(local_data['total_count'], 0)
        self.assertEqual(len(local_data['edges']), 0)

        # Recursive query, without data populated
        recursive_data = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=1,
            relations=['friend'], auth_header=member_auth_header
        )
        self.assertEqual(recursive_data['total_count'], 0)
        self.assertEqual(len(recursive_data['edges']), 0)

        # Add some data locally but no network links yet
        data: dict[str, object] = {
            'data': {
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                ),
                'asset_type': 'post',
                'asset_id': str(get_test_uuid()),
            }
        }
        await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.APPEND, data=data,
            auth_header=member_auth_header, expect_success=True
        )

        # First non-recursive query, without data populated
        local_data: dict | None = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=0,
            auth_header=member_auth_header
        )
        self.assertEqual(local_data['total_count'], 1)
        self.assertEqual(len(local_data['edges']), 1)

        # Recursive query, still without network_links
        recursive_data = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=1,
            relations=['friend'], auth_header=member_auth_header
        )
        self.assertEqual(recursive_data['total_count'], 1)
        self.assertEqual(len(recursive_data['edges']), 1)

        # Add network link from our POD to the Azure POD but no change to
        # network_links of the Azure POD
        network_link_data: dict[str, object] = {
            'data': {
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                ),
                'member_id': AZURE_POD_MEMBER_ID,
                'relation': 'friend',
            }
        }
        await call_data_api(
            self, service_id, MARKER_NETWORK_LINKS,
            action=DataRequestType.APPEND, data=network_link_data,
            auth_header=member_auth_header, expect_success=True
        )

        # Recursive query, with network_links but no relation
        # on Azure POD yet
        recursive_data = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=1,
            relations=['friend'], auth_header=member_auth_header
        )
        self.assertEqual(recursive_data['total_count'], 1)
        self.assertEqual(len(recursive_data['edges']), 1)

        await add_to_azure_pod_network_links(self, account, service_id)

        azure_member_auth_header, azure_fqdn = await get_azure_pod_jwt(
            account, TEST_DIR
        )
        # Confirm on Azure pod that we have a network_link entry
        resp: HttpResponse = await DataApiClient.call(
            service_id, MARKER_NETWORK_LINKS, DataRequestType.QUERY,
            data_filter={'member_id': {'eq': member_id}},
            timeout=TIMEOUT, headers=azure_member_auth_header,
            member_id=AZURE_POD_MEMBER_ID
        )
        azure_network_data = resp.json()
        self.assertEqual(azure_network_data['total_count'], 1)
        self.assertEqual(len(azure_network_data['edges']), 1)

        # Recursive query (depth=1), with network_links added to Azure POD
        # depth = 1: local pod + azure pod
        recursive_data = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=1,
            relations=['friend'], auth_header=member_auth_header
        )
        azure_assets_found: int = recursive_data['total_count']
        self.assertGreaterEqual(azure_assets_found, 3)
        self.assertGreaterEqual(
            len(recursive_data['edges']), azure_assets_found
        )

        # Recursive query (depth=2), with network_links added to Azure POD
        # depth = 2: local pod + azure pod + home pod
        recursive_data: dict | None = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=2,
            relations=['friend'], auth_header=member_auth_header
        )
        self.assertGreaterEqual(
            recursive_data['total_count'], azure_assets_found + 2)
        self.assertEqual(len(recursive_data['edges']), azure_assets_found + 2)

        # Recursive query (depth=3), with network_links added to Azure POD
        # depth = 3: local pod + azure pod + home pod + gcp pod
        recursive_data = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=3,
            relations=['friend'], auth_header=member_auth_header
        )
        self.assertGreaterEqual(recursive_data['total_count'], azure_assets_found + 4)
        self.assertGreaterEqual(len(recursive_data['edges']), azure_assets_found + 4)

        # Recursive query (depth=1), with remote member_id, without filter
        # depth = 1: local pod + azure pod
        recursive_data = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=1,
            remote_member_id=AZURE_POD_MEMBER_ID, auth_header=member_auth_header
        )
        self.assertGreaterEqual(recursive_data['total_count'], 3)
        self.assertGreaterEqual(len(recursive_data['edges']), 3)

        # Recursive query (depth=1), with remote member_id, with filter
        # depth = 1: local pod + azure pod
        recursive_data = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=50, depth=1,
            remote_member_id=AZURE_POD_MEMBER_ID, auth_header=member_auth_header,
            data_filter={'asset_id': {'eq': recursive_data['edges'][0]['node']['asset_id']}}
        )
        self.assertGreaterEqual(recursive_data['total_count'], 1)
        self.assertGreaterEqual(len(recursive_data['edges']), 1)

async def call_data_api(test, service_id: int, class_name: str,
                        action: DataRequestType = DataRequestType.QUERY,
                        first: int | None = None, after: str | None = None,
                        depth: int = 0, relations: set[str] | None = None,
                        remote_member_id: UUID | None = None,
                        fields: set[str] | None = None,
                        data_filter: DataFilterType | None = None,
                        data: dict[str, object] | None = None,
                        auth_header: str = None, expect_success: bool = True
                        ) -> dict | None:

    resp: HttpResponse = await DataApiClient.call(
        service_id=service_id, class_name=class_name, action=action,
        first=first, after=after, depth=depth, fields=fields,
        remote_member_id=remote_member_id, relations=relations,
        data_filter=data_filter, data=data, headers=auth_header,
        app=APP, internal=True
    )

    if expect_success:
        test.assertEqual(resp.status_code, 200)

    result: dict = resp.json()

    if not expect_success:
        return result

    if action == DataRequestType.QUERY:
        test.assertIsNotNone(result['total_count'])
    elif action in (DataRequestType.APPEND, DataRequestType.DELETE):
        test.assertIsNotNone(result)
        test.assertGreater(result, 0)
    else:
        pass

    return result


async def add_to_azure_pod_network_links(test, account: Account,
                                         service_id: int) -> None:
    azure_member_auth_header: str
    azure_fqdn: str
    azure_member_auth_header, azure_fqdn = await get_azure_pod_jwt(
        account, TEST_DIR
    )

    member: Member = await account.get_membership(service_id)
    member_id: UUID = member.member_id

    # Add network_link to Azure POD
    data: dict[str, dict[str, str]] = {
        'data': {
            'member_id': str(member.member_id),
            'relation': 'friend',
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            )
        }
    }

    resp: HttpResponse = await DataApiClient.call(
        service_id, MARKER_NETWORK_LINKS, DataRequestType.APPEND,
        data=data, timeout=TIMEOUT, headers=azure_member_auth_header,
        member_id=AZURE_POD_MEMBER_ID
    )
    append_count: int = resp.json()

    test.assertEqual(append_count, 1)

    # Confirm on Azure pod that we have a network_link entry
    resp: HttpResponse = await DataApiClient.call(
        service_id, MARKER_NETWORK_LINKS, DataRequestType.QUERY,
        data_filter={'member_id': {'eq': member_id}},
        timeout=TIMEOUT, headers=azure_member_auth_header,
        member_id=AZURE_POD_MEMBER_ID
    )
    azure_network_data: dict[str, any] = resp.json()
    test.assertEqual(azure_network_data['total_count'], 1)
    test.assertEqual(len(azure_network_data['edges']), 1)


async def populate_data_rest(test, service_id: int, class_name: str,
                             record_count: int,
                             member_auth_header: dict[str, str]
                             ) -> dict | None:
    global ALL_DATA
    ALL_DATA = []
    for count in range(0, record_count):
        vars: dict[str, any] = {
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
        ALL_DATA.append(data)

        await call_data_api(
            test, service_id, class_name, action=DataRequestType.APPEND,
            data=data, auth_header=member_auth_header, expect_success=True
        )


async def get_member_auth_header(test, member_id) -> dict[str, str]:
    resp: HttpResponse = await ApiClient.call(
        f'{BASE_URL}/v1/pod/authtoken',
        method=HttpMethod.POST,
        data={
            'username': str(member_id)[:8],
            'password': os.environ['ACCOUNT_SECRET'],
            'target_type': IdType.MEMBER.value,
            'service_id': ADDRESSBOOK_SERVICE_ID
        },
        headers={'Content-Type': 'application/json'},
        app=APP
    )
    test.assertEqual(resp.status_code, 200)
    data: dict[str, str] = resp.json()
    member_auth_header: dict[str, str] = {
        'Authorization': f'bearer {data["auth_token"]}'
    }
    return member_auth_header


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
