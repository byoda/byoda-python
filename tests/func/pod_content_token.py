#!/usr/bin/env python3

'''
Test the POD REST and Data APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license
'''

import os
import sys
import unittest

from uuid import uuid4, UUID
from datetime import datetime
from datetime import timezone, timedelta

import orjson

from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.content_key import ContentKey
from byoda.datamodel.content_key import ContentKeyStatus
from byoda.datamodel.content_key import RESTRICTED_CONTENT_KEYS_TABLE
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.table import Table

from byoda.datastore.data_store import DataStore

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter
from podserver.routers import content_token as ContentTokenRouter
from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

TEST_DIR: str = '/tmp/byoda-tests/content-token'
TEST_FILE: str = TEST_DIR + '/content_keys.json'

APP: FastAPI | None = None


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR)
        network_data: dict[str, str] = await setup_network(delete_tmp_dir=True)

        config.test_case = "TEST_CLIENT"
        config.disable_pubsub = True

        server: PodServer = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        local_service_contract: str = os.environ.get('LOCAL_SERVICE_CONTRACT')
        account: Account = await setup_account(
            network_data, test_dir=TEST_DIR,
            local_service_contract=local_service_contract, clean_pubsub=False
        )

        config.trace_server: int = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        global APP
        APP = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [
                AccountRouter, MemberRouter, AuthTokenRouter,
                AccountDataRouter, ContentTokenRouter
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

    async def test_restricted_content_key_api(self) -> None:
        account: Account = config.server.account
        member: Member = await account.get_membership(ADDRESSBOOK_SERVICE_ID)

        data_store: DataStore = config.server.data_store
        key_table: Table = data_store.get_table(
            member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )

        config.server.whitelist_dir: str = TEST_DIR

        key_id: int = 99999999
        data: dict[str, str | datetime] = {
            'key_id': key_id,
            'key': 'somesillykey',
            'not_after': datetime.now(tz=timezone.utc) + timedelta(days=1),
            'not_before': datetime.now(tz=timezone.utc) - timedelta(days=1)
        }

        # TODO: use key_table.get_cursor_hash()
        cursor: str = Table.get_cursor_hash(data, None, list(data.keys()))
        await key_table.append(
            data, cursor, origin_id=None, origin_id_type=None,
            origin_class_name=None
        )
        url: str = BASE_URL + '/v1/pod/content/token'
        asset_id: UUID = uuid4()
        query_params: dict[str, str | int] = {
            'asset_id': str(asset_id),
            'service_id': ADDRESSBOOK_SERVICE_ID,
            'class_name': 'public_assets',
            'signedby': str(uuid4()),
            'token': 'placeholder'
        }
        resp: HttpResponse = await ApiClient.call(
            url,  method=HttpMethod.GET, params=query_params, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue('content_token' in data)

        await key_table.delete(DataFilterSet({'key_id': {'eq': key_id}}))

    async def test_restricted_content_keys_table(self) -> None:
        account: Account = config.server.account
        account_member: Member | None = await account.get_membership(
            ADDRESSBOOK_SERVICE_ID
        )

        data_store: DataStore = config.server.data_store
        table: Table = data_store.get_table(
            account_member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )

        await table.delete(data_filters={})

        first_content_key: ContentKey = await ContentKey.create(
            key=uuid4(), key_id=None, not_before=None, not_after=None,
            table=table
        )
        await first_content_key.persist(table)
        # Key 1: now to 2497 (not expired)
        await test_content_keys(self, table, 1)

        second_content_key: ContentKey = await ContentKey.create(
            key=uuid4(), key_id=5,
            not_before=datetime.now(tz=timezone.utc) - timedelta(weeks=52),
            not_after=datetime.now(tz=timezone.utc) + timedelta(weeks=520),
            table=table
        )
        await second_content_key.persist(table)
        # Key_id 1 (created 1st): now to 2497 (not-expired)
        # Key_id 5 (created 2nd): -52w to + 10y (not-expired, oldest)
        await test_content_keys(self, table, 2)
        await test_content_keys(self, table, 1, ContentKeyStatus.INACTIVE)
        await test_content_keys(self, table, 0, ContentKeyStatus.EXPIRED)
        await test_content_keys(self, table, 1, ContentKeyStatus.ACTIVE)

        first_retrieved_content_key: ContentKey = \
            await ContentKey.get_active_content_key(table)
        self.assertIsNotNone(first_retrieved_content_key)
        self.assertEqual(
            second_content_key.key_id, first_retrieved_content_key.key_id
        )

        third_content_key: ContentKey = await ContentKey.create(
            key=uuid4(), key_id=None,
            not_before=datetime.now(tz=timezone.utc) - timedelta(days=1),
            not_after=datetime.now(tz=timezone.utc) + timedelta(weeks=1),
            table=table
        )
        await third_content_key.persist()
        # Key_id 1 (created 1st): now to 2497 (not-expired)
        # Key_id 5 (created 2nd): -52w to + 10y (not-expired, oldest)
        # Key_id 6 (created 3rd): -1d to + 1w (not expired)
        self.assertEqual(
            third_content_key.key_id, first_retrieved_content_key.key_id + 1
        )
        await test_content_keys(self, table, 3)
        await test_content_keys(self, table, 2, ContentKeyStatus.ACTIVE)
        await test_content_keys(self, table, 1, ContentKeyStatus.INACTIVE)
        await test_content_keys(self, table, 0, ContentKeyStatus.EXPIRED)

        second_retrieved_content_key: ContentKey = \
            await ContentKey.get_active_content_key(table=table)
        self.assertIsNotNone(first_retrieved_content_key)
        self.assertEqual(
            second_content_key.key_id, second_retrieved_content_key.key_id
        )

        fourth_content_key: ContentKey = await ContentKey.create(
            key=uuid4(), key_id=None,
            not_before=datetime.now(tz=timezone.utc) - timedelta(days=2),
            not_after=datetime.now(tz=timezone.utc) - timedelta(days=1),
            table=table
        )
        await fourth_content_key.persist()
        # Key_id 1 (created 1st): now to 2497 (not-expired)
        # Key_id 5 (created 2nd): -52w to + 10y (not-expired, oldest)
        # Key_id 6 (created 3rd): -1d to + 1w (not expired)
        # Key_id 7 (created 4th): -2d to -1d (expired)

        await test_content_keys(self, table, 4)
        await test_content_keys(self, table, 2, ContentKeyStatus.ACTIVE)
        await test_content_keys(self, table, 1, ContentKeyStatus.INACTIVE)
        await test_content_keys(self, table, 1, ContentKeyStatus.EXPIRED)

        second_retrieved_content_key: ContentKey | None = \
            await ContentKey.get_active_content_key(table=table)
        self.assertIsNotNone(second_retrieved_content_key)
        self.assertEqual(
            second_content_key.key_id, second_retrieved_content_key.key_id
        )

    async def test_restricted_content_token(self) -> None:
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)

        data_store: DataStore = config.server.data_store
        table: Table = data_store.get_table(
            member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )

        await table.delete(data_filters={})

        content_key: ContentKey = await ContentKey.create(
            key=str(uuid4()), key_id=100,
            not_before=datetime.now(tz=timezone.utc) - timedelta(days=1),
            not_after=datetime.now(tz=timezone.utc) + timedelta(days=1),
        )
        await content_key.persist(table=table)

        asset_id = UUID('3516188b-bf6d-47bf-adcd-48cc9870862b')
        token = content_key.generate_token(
            service_id, member.member_id, asset_id
        )

        self.assertIsNotNone(token)

        second_token = content_key.generate_token(
            service_id, member.member_id, asset_id
        )

        self.assertEqual(token, second_token)

        query_params = content_key.generate_url_query_parameters(
            service_id, member.member_id, asset_id
        )
        self.assertIsNotNone(query_params)

        self.assertEqual(
            query_params,
            '&'.join(
                [
                    f'service_id={service_id}',
                    f'member_id={member.member_id}',
                    f'asset_id={asset_id}'
                ]
            )
        )


async def test_content_keys(test, table, keys_expected,
                            status: ContentKeyStatus | None = None
                            ) -> list[ContentKey]:
    keys: list[ContentKey] = await ContentKey.get_content_keys(
        table=table, status=status
    )
    test.assertEqual(len(keys), keys_expected)
    return keys


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
