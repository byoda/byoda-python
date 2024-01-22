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
from typing import TypeVar
from datetime import datetime
from datetime import timezone

from anyio import sleep

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType
from byoda.datatypes import AnyScalarType
from byoda.datatypes import DataFilterType

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.data_api_client import DataApiClient

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

from tests.lib.auth import get_member_auth_header
from tests.lib.auth import get_azure_pod_jwt
from tests.lib.util import get_test_uuid
from tests.lib.util import call_data_api

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

PodServer = TypeVar('PodServer')

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
            await member.enable_data_apis(
                APP, server.data_store, server.cache_store
            )

    @classmethod
    async def asyncTearDown(self):
        await ApiClient.close_all()

    async def test_pod_rest_data_api_append_with_origin(self):
        server: PodServer = config.server
        account: Account = server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        member_auth_header = await get_member_auth_header(
            service_id=service_id, test=self, app=APP,
        )

        # Requirements for settign origin_id/origin_id_type/origin_class_name
        # 0: caller must have APPEND permission on the class
        # 1: the member of the pod itself must be calling the Append API of pod
        # 2: depth must be 0 and remote_member_id must be None
        # 3: class_name must not be cache-only
        class_name: str = 'incoming_assets'
        data: dict[str, AnyScalarType] = {
            'origin_id': member.member_id,
            'origin_id_type': IdType.MEMBER.value,
            'origin_class_name': 'network_assets',
            'data': {
                'asset_id': str(get_test_uuid()),
                'asset_type': 'post',
                'created_timestamp': datetime.now(tz=timezone.utc).isoformat(),
            }
        }
        resp = await DataApiClient.call(
            service_id=service_id, class_name=class_name,
            action=DataRequestType.APPEND,
            depth=0, data=data,
            headers=member_auth_header, app=APP, internal=True
        )
        self.assertEqual(resp.status_code, 200)

        with self.assertRaises(ByodaRuntimeError):
            class_name: str = 'public_assets'
            resp: HttpResponse = await DataApiClient.call(
                service_id=service_id, class_name=class_name,
                action=DataRequestType.APPEND,
                depth=0, data=data,
                headers=member_auth_header, app=APP, internal=True
            )

        with self.assertRaises(ByodaRuntimeError):
            azure_auth_header, _ = await get_azure_pod_jwt(account, TEST_DIR)
            class_name: str = 'network_invites'
            data: dict[str, AnyScalarType] = {
                'data': {
                    'member_id': str(get_test_uuid()),
                    'relation': 'friend',
                    'created_timestamp': datetime.now(tz=timezone.utc).isoformat(),
                },
                'origin_id': member.member_id,
                'origin_id_type': IdType.MEMBER.value,
                'origin_class_name': 'network_assets',
            }
            resp = await DataApiClient.call(
                service_id=service_id, class_name=class_name,
                action=DataRequestType.APPEND,
                depth=0, data=data,
                headers=azure_auth_header, app=APP, internal=True
            )

    async def test_pod_rest_data_api_update_jwt(self):
        service_id: int = ADDRESSBOOK_SERVICE_ID

        member_auth_header = await get_member_auth_header(
            service_id=service_id, test=self, app=APP,
        )
        total_records: int = 5
        class_name: str = 'network_assets'
        await populate_data_rest(
            self, service_id, class_name, total_records, member_auth_header,
            app=APP
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
        updated_count: dict[str, object] | int | None = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.UPDATE,
            data_filter={'asset_id': {'eq': ALL_DATA[0]['data']['asset_id']}},
            data=update_data,
            auth_header=member_auth_header, expect_success=True, app=APP
        )
        self.assertEqual(updated_count, 1)

        all_data: dict[str, object] | int | None = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            data_filter={'asset_id': {'eq': asset_id}},
            auth_header=member_auth_header, app=APP
        )
        self.assertEqual(all_data['total_count'], 1)
        node: dict[str, any] = all_data['edges'][0]['node']
        self.assertEqual(node['asset_type'], 'audio')
        self.assertEqual(node['asset_id'], str(asset_id))

        with self.assertRaises(ByodaRuntimeError):
             await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter=None,
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter={'asset_id': None},
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter={'asset_id': {}},
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter={'asset_id': {'blah': None}},
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        with self.assertRaises(KeyError):
            await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.UPDATE, data=update_data,
                data_filter={'asset_id': {'blah': 'blah'}},
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        updated_count = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.UPDATE, data=update_data,
            data_filter={'asset_id': {'eq': get_test_uuid()}},
            auth_header=member_auth_header, expect_success=True, app=APP
        )
        self.assertEqual(updated_count, 0)

        updated_count = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.UPDATE, data=update_data,
            data_filter={'asset_id': {'ne': asset_id}},
            auth_header=member_auth_header, expect_success=True, app=APP
        )
        self.assertEqual(updated_count, 4)


    async def test_pod_rest_data_api_delete_jwt(self):
        service_id: int = ADDRESSBOOK_SERVICE_ID

        member_auth_header = await get_member_auth_header(
            service_id=service_id, test=self, app=APP,
        )
        total_records: int = 10
        class_name: str = 'network_assets'
        await populate_data_rest(
            self, service_id, class_name, total_records, member_auth_header,
            app=APP
        )

        with self.assertRaises(ByodaRuntimeError):
             await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.DELETE, data_filter=None,
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.DELETE, data_filter={'asset_id': None},
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.DELETE, data_filter={'asset_id': {}},
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        with self.assertRaises(ByodaRuntimeError):
            await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.DELETE, data_filter={'asset_id': {'blah': None}},
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        with self.assertRaises(ValueError):
            await call_data_api(
                service_id, class_name, test=self,
                action=DataRequestType.DELETE, data_filter={'asset_id': {'blah': 'blah'}},
                auth_header=member_auth_header, expect_success=False, app=APP
            )

        # No items deleted because we are specifying a bogus asset_id
        deleted_count = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.DELETE,
            data_filter={'asset_id': {'eq': get_test_uuid()}},
            auth_header=member_auth_header, expect_success=False, app=APP
        )
        self.assertEqual(deleted_count, 0)

        # Get some data so we know what data we can use to delete
        all_data = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=3,
            auth_header=member_auth_header, app=APP
        )
        self.assertEqual(all_data['total_count'], 3)

        # Delete one item
        asset = all_data['edges'][1]['node']
        deleted_count = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.DELETE,
            data_filter={'asset_id': {'eq': asset['asset_id']}},
            auth_header=member_auth_header, expect_success=True, app=APP
        )
        self.assertEqual(deleted_count, 1)

        # delete all items except the second node
        asset = all_data['edges'][2]['node']
        deleted_count = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.DELETE,
            data_filter={'asset_id': {'ne': asset['asset_id']}},
            auth_header=member_auth_header, expect_success=True, app=APP
        )
        self.assertEqual(deleted_count, 8)

        # Delete the remaining one item
        deleted_count = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.DELETE,
            data_filter={'asset_type': {'ne': ''}},
            auth_header=member_auth_header,
            expect_success=True, app=APP
        )
        self.assertEqual(deleted_count, 1)

    async def test_pod_rest_data_api_filters_jwt(self):
        service_id: int = ADDRESSBOOK_SERVICE_ID

        member_auth_header = await get_member_auth_header(
            service_id=service_id, test=self, app=APP,
        )
        total_records: int = 50
        class_name: str = 'network_assets'
        asset_data: list[dict[str, object]] = await populate_data_rest(
            self, service_id, class_name, total_records, member_auth_header,
            app=APP
        )

        all_data = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header, app=APP
        )
        self.assertEqual(all_data['total_count'], total_records)
        self.assertEqual(
            all_data['edges'][-1]['cursor'], all_data['page_info']['end_cursor']
        )

        data_filter: DataFilterType = {
            'ingest_status': {'eq': 'published'}
        }

        filter_batch = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            first=None, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header, app=APP
        )

        self.assertEqual(len(filter_batch['edges']), total_records/2)

        asset_id: str = all_data['edges'][0]['node']['asset_id']
        data_filter: DataFilterType = {
            'asset_id': {'eq': asset_id}
        }

        filter_batch = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            first=None, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header, app=APP
        )

        self.assertEqual(len(filter_batch['edges']), 1)

        title: str = all_data['edges'][0]['node']['title']
        data_filter: DataFilterType = {
            'asset_id': {'eq': asset_id},
            'title': {'eq': title}
        }

        filter_batch = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            first=None, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header, app=APP
        )

        self.assertEqual(len(filter_batch['edges']), 1)

        data_filter: DataFilterType = {
            'asset_id': {'ne': asset_id}
        }
        filter_batch = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            first=100, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header, app=APP
        )

        self.assertEqual(len(filter_batch['edges']), total_records-1)

        # When trying to apply to filters with the same key, you end up
        # with just one filter because of the duplicate key
        data_filter: DataFilterType = {
            'asset_id': {'ne': asset_id},
            'asset_id': {'ne': all_data['edges'][1]['node']['asset_id']},
        }
        filter_batch = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            first=100, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header, app=APP
        )

        self.assertEqual(len(filter_batch['edges']), total_records-1)

        data_filter: DataFilterType = {
            'asset_id': {'ne': asset_id},
            'title': {'ne': title},
        }
        filter_batch = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            first=100, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header, app=APP
        )

        self.assertEqual(len(filter_batch['edges']), total_records-1)

        data_filter: DataFilterType = {
            'asset_id': {'ne': asset_id},
            'title': {'ne': all_data['edges'][1]['node']['title']},
        }
        filter_batch = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            first=100, after=None,
            data_filter=data_filter,
            auth_header=member_auth_header, app=APP
        )

        self.assertEqual(len(filter_batch['edges']), total_records-2)

        # Filter on datetime, which is special case for Sqlite as
        # we store datetime as floats, which are not exact
        asset_timestamp: str = asset_data[0]['data']['created_timestamp']
        data_filter: DataFilterType = {
            'created_timestamp': {'at': asset_timestamp}
        }

    async def test_pod_rest_data_api_pagination_jwt(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        member_auth_header = await get_member_auth_header(
            service_id=service_id, test=self, app=APP,
        )
        total_records: int = 50
        batch_size: int = 20
        class_name: str = 'network_assets'
        await populate_data_rest(
            self, service_id, class_name, total_records, member_auth_header,
            app=APP
        )

        all_data = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header, app=APP
        )
        self.assertEqual(all_data['total_count'], total_records)
        self.assertEqual(
            all_data['edges'][-1]['cursor'], all_data['page_info']['end_cursor']
        )

        first_batch = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=batch_size,
            auth_header=member_auth_header, app=APP
        )
        after = first_batch['page_info']['end_cursor']
        self.assertEqual(after, all_data['edges'][19]['cursor'])

        second_batch = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            first=batch_size, after=after,
            auth_header=member_auth_header, app=APP
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
            service_id, class_name, test=self,
            action=DataRequestType.QUERY,
            first=batch_size, after=after, fields=fields,
            auth_header=member_auth_header, app=APP
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

    async def test_datetime_comparisons(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        member_auth_header = await get_member_auth_header(
            service_id=service_id, test=self, app=APP,
        )
        total_records: int = 5
        class_name: str = 'network_assets'
        all_data: list[dict[str, object]] = await populate_data_rest(
            self, service_id, class_name, total_records, member_auth_header,
            app=APP, delay=1/total_records,
        )

        created_timestamp = all_data[1]['data']['created_timestamp']
        data_filter = {
            'created_timestamp': {'at': created_timestamp}
        }
        data = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header, data_filter=data_filter, app=APP
        )
        self.assertEqual(data['total_count'], 1)

        data_filter = {
            'created_timestamp': {'nat': created_timestamp}
        }
        data = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header, data_filter=data_filter, app=APP
        )
        self.assertEqual(data['total_count'], 4)

        data_filter = {
            'created_timestamp': {'before': created_timestamp}
        }
        data = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header, data_filter=data_filter, app=APP
        )
        self.assertEqual(data['total_count'], 1)

        data_filter = {
            'created_timestamp': {'after': created_timestamp}
        }
        data = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header, data_filter=data_filter, app=APP
        )
        self.assertEqual(data['total_count'], 3)

        data_filter = {
            'created_timestamp': {'atbefore': created_timestamp}
        }
        data = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header, data_filter=data_filter, app=APP
        )
        self.assertEqual(data['total_count'], 2)

        data_filter = {
            'created_timestamp': {'atafter': created_timestamp}
        }
        data = await call_data_api(
            service_id, class_name, test=self,
            action=DataRequestType.QUERY, first=total_records,
            auth_header=member_auth_header, data_filter=data_filter, app=APP
        )
        self.assertEqual(data['total_count'], 4)


async def populate_data_rest(test, service_id: int, class_name: str,
                             record_count: int,
                             member_auth_header: dict[str, str],
                             app: FastAPI = None, delay=None
                             ) -> dict | None:
    global ALL_DATA
    ALL_DATA = []
    for count in range(0, record_count):
        asset_id: UUID = get_test_uuid()
        vars: dict[str, any] = {
            'created_timestamp': str(
                datetime.now(tz=timezone.utc).isoformat()
            ),
            'asset_type': 'post',
            'asset_id': str(asset_id),
            'creator': f'test account #{count}',
            'title': f'test asset-{count}',
            'subject': 'just a test asset',
            'contents': 'some utf-8 markdown string',
            'keywords': ["just", "testing"],
            'ingest_status': ['published', 'external'][count % 2],
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
            ],
            'claims': [
                {
                    'claim_id': get_test_uuid(),
                    'claims': ['violence:4', 'scary:5'],
                    'issuer_id': get_test_uuid(),
                    'issuer_type': 'app',
                    'object_type': 'network_assets',
                    'keyfield': 'asset_id',
                    'keyfield_id': asset_id,
                    'object_fields': ['asset_id', 'title', 'contents'],
                    'requester_id': get_test_uuid(),
                    'requester_type': 'member',
                    'signature': 'blah',
                    'signature_format_version': 1,
                    'signature_timestamp': str(
                        datetime.now(tz=timezone.utc).isoformat()
                    ),
                    'signature_url': 'https://signature_url',
                    'renewal_url': 'https://renewal_url',
                    'confirmation_url': 'https://confirmation_url',
                    'cert_fingerprint': 'abcde',
                    'cert_expiration': str(
                        datetime.now(tz=timezone.utc).isoformat()
                    )
                }
            ]
        }

        data: {str, dict[str, AnyScalarType]} = {
            'query_id': get_test_uuid(),
            'data': vars
        }
        ALL_DATA.append(data)

        await call_data_api(
            service_id, class_name, test=test,
            action=DataRequestType.APPEND,
            data=data, auth_header=member_auth_header, expect_success=True,
            app=APP
        )
        if delay:
            await sleep(1)

    return ALL_DATA


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
