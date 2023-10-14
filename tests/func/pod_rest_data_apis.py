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

from copy import copy
from uuid import UUID
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType
from byoda.datatypes import DATA_API_URL

from byoda.models.data_api_models import AnyScalarType
from byoda.models.data_api_models import DataFilterType

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


from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import mock_environment_vars
from tests.lib.util import get_test_uuid

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID


# Settings must match config.yml used by directory server
NETWORK: str = config.DEFAULT_NETWORK

# This must match the test directory in tests/lib/testserver.p
TEST_DIR: str = '/tmp/byoda-tests/pod-rest-data-apis'

APP: FastAPI | None = None

ALL_DATA: list[dict[str, AnyScalarType]] = []


class TestRestDataApis(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=True)

        config.test_case = 'TEST_CLIENT'
        config.disable_pubsub = True

        server: PodServer = config.server

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

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

    async def test_pod_rest_data_api_update_jwt(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        member_auth_header = await get_member_auth_header(
            self, member.member_id
        )

        total_records: int = 5
        class_name: str = 'network_assets'
        await populate_data_rest(
            self, service_id, class_name, total_records, member_auth_header
        )

        # update one item of the array
        asset_id = get_test_uuid()
        update_data: dict[str, dict[str, AnyScalarType]] = {
            'data': {
                'asset_id': asset_id,
                'asset_type': 'audio',
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                ),
            }
        }
        updated_count = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.UPDATE,
            data_filter={'asset_id': {'eq': ALL_DATA[0]['data']['asset_id']}},
            data=update_data,
            auth_header=member_auth_header, expect_success=True
        )
        self.assertEqual(updated_count, 1)

        all_data = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.QUERY,
            data_filter={'asset_id': {'eq': asset_id}},
            auth_header=member_auth_header
        )
        self.assertEqual(all_data['total_count'], 1)
        node = all_data['edges'][0]['node']
        self.assertEqual(node['asset_type'], 'audio')
        self.assertEqual(node['asset_id'], str(asset_id))

        with self.assertRaises(ByodaRuntimeError):
             await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter=None,
                auth_header=member_auth_header, expect_success=False
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter={'asset_id': None},
                auth_header=member_auth_header, expect_success=False
            )

        with self.assertRaises(ValueError):
            await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter={'asset_id': {}},
                auth_header=member_auth_header, expect_success=False
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter={'asset_id': {'blah': None}},
                auth_header=member_auth_header, expect_success=False
            )

        with self.assertRaises(KeyError):
            await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter={'asset_id': {'blah': 'blah'}},
                auth_header=member_auth_header, expect_success=False
            )

        updated_count = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.UPDATE, data=update_data,
            data_filter={'asset_id': {'eq': get_test_uuid()}},
            auth_header=member_auth_header, expect_success=True
        )
        self.assertEqual(updated_count, 0)

        updated_count = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.UPDATE, data=update_data,
            data_filter={'asset_id': {'ne': asset_id}},
            auth_header=member_auth_header, expect_success=True
        )
        self.assertEqual(updated_count, 4)


    async def test_pod_rest_data_api_delete_jwt(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        member_auth_header = await get_member_auth_header(
            self, member.member_id
        )

        total_records: int = 10
        class_name: str = 'network_assets'
        await populate_data_rest(
            self, service_id, class_name, total_records, member_auth_header
        )

        with self.assertRaises(ByodaRuntimeError):
             await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.DELETE, data_filter=None,
                auth_header=member_auth_header, expect_success=False
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.DELETE, data_filter={'asset_id': None},
                auth_header=member_auth_header, expect_success=False
            )

        with self.assertRaises(ValueError):
            await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.DELETE, data_filter={'asset_id': {}},
                auth_header=member_auth_header, expect_success=False
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.DELETE, data_filter={'asset_id': {'blah': None}},
                auth_header=member_auth_header, expect_success=False
            )

        with self.assertRaises(KeyError):
            await call_data_api(
                self, ADDRESSBOOK_SERVICE_ID, class_name,
                action=DataRequestType.DELETE, data_filter={'asset_id': {'blah': 'blah'}},
                auth_header=member_auth_header, expect_success=False
            )

        # No items deleted because we are specifying a bogus asset_id
        deleted_count = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.DELETE, data_filter={'asset_id': {'eq': get_test_uuid()}},
            auth_header=member_auth_header, expect_success=False
        )
        self.assertEqual(deleted_count, 0)

        # Get some data so we know what data we can use to delete
        all_data = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.QUERY, first=3,
            auth_header=member_auth_header
        )
        self.assertEqual(all_data['total_count'], 3)

        # Delete one item
        asset = all_data['edges'][1]['node']
        deleted_count = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.DELETE, data_filter={'asset_id': {'eq': asset['asset_id']}},
            auth_header=member_auth_header, expect_success=True
        )
        self.assertEqual(deleted_count, 1)

        # delete all items except the second node
        asset = all_data['edges'][2]['node']
        deleted_count = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.DELETE, data_filter={'asset_id': {'ne': asset['asset_id']}},
            auth_header=member_auth_header, expect_success=True
        )
        self.assertEqual(deleted_count, 8)

        # Delete the remaining one item
        deleted_count = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.DELETE, data_filter={'asset_id': {'ne': ''}},
            auth_header=member_auth_header, expect_success=True
        )
        self.assertEqual(deleted_count, 1)

    async def test_pod_rest_data_api_filters_jwt(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        member_auth_header = await get_member_auth_header(
            self, member.member_id
        )

        total_records: int = 50
        class_name: str = 'network_assets'
        await populate_data_rest(
            self, service_id, class_name, total_records, member_auth_header
        )

        all_data = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header
        )
        self.assertEqual(all_data['total_count'], total_records)
        self.assertEqual(
            all_data['edges'][-1]['cursor'], all_data['page_info']['end_cursor']
        )

        asset_id: str = all_data['edges'][0]['node']['asset_id']
        data_filter: DataFilterType = {
            'asset_id': {'eq': asset_id}
        }

        filter_batch = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY,
            first=None, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header
        )

        self.assertEqual(len(filter_batch['edges']), 1)

        title: str = all_data['edges'][0]['node']['title']
        data_filter: DataFilterType = {
            'asset_id': {'eq': asset_id},
            'title': {'eq': title}
        }

        filter_batch = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY,
            first=None, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header
        )

        self.assertEqual(len(filter_batch['edges']), 1)

        data_filter: DataFilterType = {
            'asset_id': {'ne': asset_id}
        }
        filter_batch = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY,
            first=100, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header
        )

        self.assertEqual(len(filter_batch['edges']), total_records-1)

        # When trying to apply to filters with the same key, you end up
        # with just one filter because of the duplicate key
        data_filter: DataFilterType = {
            'asset_id': {'ne': asset_id},
            'asset_id': {'ne': all_data['edges'][1]['node']['asset_id']},
        }
        filter_batch = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY,
            first=100, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header
        )

        self.assertEqual(len(filter_batch['edges']), total_records-1)

        data_filter: DataFilterType = {
            'asset_id': {'ne': asset_id},
            'title': {'ne': title},
        }
        filter_batch = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY,
            first=100, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header
        )

        self.assertEqual(len(filter_batch['edges']), total_records-1)

        data_filter: DataFilterType = {
            'asset_id': {'ne': asset_id},
            'title': {'ne': all_data['edges'][1]['node']['title']},
        }
        filter_batch = await call_data_api(
            self, service_id, class_name,
            action=DataRequestType.QUERY,
            first=100, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header
        )

        self.assertEqual(len(filter_batch['edges']), total_records-2)

    async def test_pod_rest_data_api_mutate_jwt(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        member_auth_header = await get_member_auth_header(
            self, member.member_id
        )

        class_name = 'person'
        data = {
            'data': {
                'given_name': 'givenname',
                'family_name': 'familyname',
                'homepage_url': 'https://www.byoda.org',
                'email': 'steven@byoda.org',
                'avatar_url': 'https://dev.null',
            }
        }
        await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.MUTATE, data=data,
            auth_header=member_auth_header,
        )

        result: dict[str, str] = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.QUERY,
            auth_header=member_auth_header,
        )
        result_data = result['edges'][0]['node']
        data['data']['additional_names'] = None
        self.assertEqual(data['data'], result_data)

    async def test_object_fields(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        member_auth_header = await get_member_auth_header(
            self, member.member_id
        )

        class_name = 'person'
        data = {
            'data': {
                'given_name': 'givenname',
                'family_name': 'familyname',
                'homepage_url': 'https://www.byoda.org',
                'email': 'steven@byoda.org',
                'avatar_url': 'https://dev.null',
            }
        }
        await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.MUTATE, data=data,
            auth_header=member_auth_header,
        )

        fields: list[str] = ['given_name', 'family_name', 'homepage_url']
        result: dict[str, str] = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.QUERY, fields=fields,
            auth_header=member_auth_header,
        )
        result_data = result['edges'][0]['node']

        # Requested fields
        self.assertIsNotNone(result_data['given_name'])
        self.assertIsNotNone(result_data['family_name'])
        self.assertIsNotNone(result_data['homepage_url'])

        # Not requested but required
        self.assertIsNotNone(result_data['email'])

        # Not requested nor required
        self.assertIsNone(result_data['avatar_url'])

    async def test_pod_rest_data_api_pagination_jwt(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        member_auth_header = await get_member_auth_header(
            self, member.member_id
        )

        total_records: int = 50
        batch_size: int = 20
        class_name: str = 'network_assets'
        await populate_data_rest(
            self, service_id, class_name, total_records, member_auth_header
        )

        all_data = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header
        )
        self.assertEqual(all_data['total_count'], total_records)
        self.assertEqual(
            all_data['edges'][-1]['cursor'], all_data['page_info']['end_cursor']
        )

        first_batch = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.QUERY, first=batch_size,
            auth_header=member_auth_header
        )
        after = first_batch['page_info']['end_cursor']
        self.assertEqual(after, all_data['edges'][19]['cursor'])

        second_batch = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.QUERY,
            first=batch_size, after=after,
            auth_header=member_auth_header
        )
        self.assertEqual(
            second_batch['edges'][0]['cursor'], all_data['edges'][20]['cursor']
        )

        # Check for data to nested-arrays that are not represented
        # in the service schema as separate data objects
        asset = all_data['edges'][0]['node']
        self.assertEqual(len(asset['video_thumbnails']), 2)
        self.assertEqual(len(asset['video_chapters']), 3)
        self.assertEqual(len(asset['keywords']), 2)

        ###
        ### Check queries that specify which fields may be returned
        ###

        fields: list[str] = [
            'asset_id', 'publisher', 'keywords', 'video_chapters'
        ]

        fields_batch = await call_data_api(
            self, ADDRESSBOOK_SERVICE_ID, class_name,
            action=DataRequestType.QUERY,
            first=batch_size, after=after, fields=fields,
            auth_header=member_auth_header
        )

        self.assertEqual(len(fields_batch['edges']), batch_size)
        for edge in fields_batch['edges'] or []:
            node = edge['node']

            # requested field
            self.assertIsNotNone(node['asset_id'])
            self.assertEqual(len(node['keywords']), 2)

            # requested array
            self.assertNotEqual(len(node['video_chapters']), 0)

            # We did not request video_thumbnails, which is an array
            self.assertIsNone(node['video_thumbnails'])

            # We did not populate the 'publisher' field so it should
            # not be included in the response
            self.assertIsNone(node['publisher'])

            # These are required fields so should be included
            # in the response even if we did not request them
            self.assertIsNotNone(node['created_timestamp'])
            self.assertIsNotNone(node['asset_type'])

async def call_data_api(test, service_id: int, class_name: str,
                        action: DataRequestType = DataRequestType.QUERY,
                        first: int | None = None, after: str | None = None,
                        depth: int = 0, fields: set[str] | None = None,
                        data_filter: DataFilterType | None = None,
                        data: dict[str, object] | None = None,
                        auth_header: str = None, expect_success: bool = True
                        ) -> dict | None:

    resp = await DataApiClient.call(
        service_id=service_id, class_name=class_name, action=action,
        first=first, after=after, depth=depth, fields=fields,
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


async def populate_data_rest(test, service_id: int, class_name: str,
                             record_count: int,
                             member_auth_header: dict[str, str]
                             ) -> dict | None:
    global ALL_DATA
    ALL_DATA = []
    for count in range(0, record_count):
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
