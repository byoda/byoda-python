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
from datetime import UTC
from datetime import datetime
from datetime import timedelta

import httpx

from yaml import safe_load as yaml_safe_loader
from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.content_key import ContentKey
from byoda.datamodel.content_key import ContentKeyStatus
from byoda.datamodel.content_key import RESTRICTED_CONTENT_KEYS_TABLE
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.sqltable import SqlTable
from byoda.datamodel.monetization import Monetizations
from byoda.datamodel.monetization import BurstMonetization

from byoda.datatypes import IdType

from byoda.datastore.data_store import DataStore

from byoda.storage.postgres import PostgresStorage

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

from tests.lib.util import get_test_uuid
from tests.lib.defines import BASE_URL      # noqa: F401
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import BYOTUBE_SERVICE_ID
TEST_DIR: str = '/tmp/byoda-tests/content-token'
TEST_FILE: str = TEST_DIR + '/content_keys.json'

APP: FastAPI | None = None

ASSET_TABLE: str = 'public_assets'


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

        config.trace_server = os.environ.get(
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

        asset_table: SqlTable = data_store.get_table(
            member.member_id, ASSET_TABLE
        )
        asset_id: str = str(get_test_uuid())
        asset: dict[str, any] = {
            'asset_id': asset_id,
            'created_timestamp': datetime.now(tz=UTC).timestamp(),
            'asset_type': 'video',
            'monetizations': Monetizations.from_monetization_instance(
                BurstMonetization()
            ).as_dict()
        }
        asset_cursor: str = SqlTable.get_cursor_hash(
            asset, None, list(asset.keys())
        )
        await asset_table.append(asset, asset_cursor, None, None, None)

        config.server.whitelist_dir = TEST_DIR

        key_id: int = 99999999
        data: dict[str, str | datetime] = {
            'key_id': key_id,
            'key': 'somesillykey',
            'not_after': datetime.now(tz=UTC) + timedelta(days=1),
            'not_before': datetime.now(tz=UTC) - timedelta(days=1)
        }

        key_table: SqlTable = data_store.get_table(
            member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )
        cursor: str = SqlTable.get_cursor_hash(data, None, list(data.keys()))
        await key_table.append(
            data, cursor, origin_id=None, origin_id_type=None,
            origin_class_name=None
        )

        # TODO: refactor test to use BYOTube service instead of ADDRESSBOOK
        # because we can't get an attestation for ADDRESSBOOK service
        # test is covered by tests/integration/pod_content_token.py
        #
        # attest: dict[str, any] = await self.get_attestation()
        # url: str = BASE_URL + '/v1/pod/content/token'
        # query_params: dict[str, str | int] = {
        #     'asset_id': asset_id,
        #     'service_id': ADDRESSBOOK_SERVICE_ID,
        #     'class_name': 'public_assets',
        #     'signedby': str(uuid4()),
        #     'token': 'placeholder'
        # }
        #
        # resp: HttpResponse = await ApiClient.call(
        #     url,  method=HttpMethod.POST, data=query_params, app=APP
        # )
        # self.assertEqual(resp.status_code, 200)
        # data = resp.json()
        # self.assertTrue('content_token' in data)

        await key_table.delete(
            DataFilterSet({'key_id': {'eq': key_id}}),
            placeholder_function=PostgresStorage.get_named_placeholder
        )

    async def test_restricted_content_keys_table(self) -> None:
        account: Account = config.server.account
        account_member: Member | None = await account.get_membership(
            ADDRESSBOOK_SERVICE_ID
        )

        data_store: DataStore = config.server.data_store
        table: SqlTable = data_store.get_table(
            account_member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )

        data_filters = DataFilterSet(
            {
                'not_after': {
                    'after': datetime.now(tz=UTC) - timedelta(days=3650)
                }
            }
        )
        await table.delete(
            data_filters=data_filters,
            placeholder_function=PostgresStorage.get_named_placeholder
        )

        first_content_key: ContentKey = await ContentKey.create(
            key=uuid4(), key_id=None, not_before=None, not_after=None,
            table=table
        )
        await first_content_key.persist(table)
        # Key 1: now to 2497 (not expired)
        await test_content_keys(self, table, 1)

        second_content_key: ContentKey = await ContentKey.create(
            key=uuid4(), key_id=5,
            not_before=datetime.now(tz=UTC) - timedelta(weeks=52),
            not_after=datetime.now(tz=UTC) + timedelta(weeks=520),
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
            not_before=datetime.now(tz=UTC) - timedelta(days=1),
            not_after=datetime.now(tz=UTC) + timedelta(weeks=1),
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
            not_before=datetime.now(tz=UTC) - timedelta(days=2),
            not_after=datetime.now(tz=UTC) - timedelta(days=1),
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
        table: SqlTable = data_store.get_table(
            member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )

        data_filters = DataFilterSet(
            {
                'not_after': {
                    'after': datetime.now(tz=UTC) - timedelta(days=3650)
                }
            }
        )
        await table.delete(
            data_filters=data_filters,
            placeholder_function=PostgresStorage.get_named_placeholder
        )

        content_key: ContentKey = await ContentKey.create(
            key=str(uuid4()), key_id=100,
            not_before=datetime.now(tz=UTC) - timedelta(days=1),
            not_after=datetime.now(tz=UTC) + timedelta(days=1),
        )
        await content_key.persist(table=table)

        asset_id = UUID('3516188b-bf6d-47bf-adcd-48cc9870862b')
        token: str = content_key.generate_token(
            service_id, member.member_id, asset_id
        )

        self.assertIsNotNone(token)

        second_token: str = content_key.generate_token(
            service_id, member.member_id, asset_id
        )

        self.assertEqual(token, second_token)

        query_params: str = content_key.generate_url_query_parameters(
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

    async def get_attestation(self) -> dict[str, any]:
        pay_jwt: str = await self.get_byopay_jwt_for_pod()
        pay_auth: dict[str, str] = {'Authorization': f'bearer {pay_jwt}'}
        pay_url: str = 'https://staging.byopay.me/api/v1/pay'

        resp: HttpResponse = httpx.get(
            f'{pay_url}/burst/attest',
            headers=pay_auth
        )
        self.assertEqual(resp.status_code, 200)
        burst_data = resp.json()
        self.assertIsNotNone(burst_data)
        self.assertTrue('claims' in burst_data)
        self.assertTrue(isinstance(burst_data['claims'], list))
        self.assertEqual(len(burst_data['claims']), 1)
        self.assertIsNotNone(burst_data['claims'][0]['signature'])

        return burst_data

    def get_byopay_data(self) -> dict[str, str | int]:
        with open('tests/collateral/local/dathes-pod.yml', 'r') as file_desc:
            test_config = yaml_safe_loader(file_desc)

            return test_config

    async def get_byopay_jwt_for_pod(self) -> str:
        test_config: dict[str, any] = self.get_byopay_data()
        fqdn: str = test_config['fqdn']

        base_url: str = f'https://{fqdn}/api/v1/pod'
        # Get pod account_jwt
        resp: HttpResponse = httpx.post(
            f'{base_url}/authtoken',
            json={
                'username': test_config['username'],
                'password': test_config['password'],
                'target_type': IdType.ACCOUNT.value,
            },
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(resp.status_code, 200)
        resp_data: dict[str, str] = resp.json()
        account_jwt: str = resp_data.get('auth_token')
        self.assertTrue(isinstance(account_jwt, str))
        auth_header: dict[str, str] = {
            'Authorization': f'bearer {account_jwt}'
        }

        #
        # Now we'll get a member JWT by using the account JWT and
        # the Data API call will fail while Data API call with
        # member JWT will succeed
        #
        resp = httpx.post(
            f'{base_url}/authtoken/service_id/{test_config['service_id']}',
            headers=auth_header
        )
        self.assertEqual(resp.status_code, 200)
        resp_data = resp.json()
        member_jwt: str = resp_data.get('auth_token')
        self.assertTrue(isinstance(member_jwt, str))
        member_auth: dict[str, str] = {'Authorization': f'bearer {member_jwt}'}

        #
        # now we'll get the external app JWT from the pod
        #
        data: dict[str, int] = {
            'service_id': BYOTUBE_SERVICE_ID,
            'target_id': test_config['app_id'],
            'target_type': IdType.APP.value,

        }
        resp = httpx.post(
            f'{base_url}/authtoken/remote',
            headers=member_auth, json=data
        )
        self.assertEqual(resp.status_code, 200)
        resp_data = resp.json()
        external_app_jwt: str = resp_data.get('auth_token')
        self.assertTrue(isinstance(external_app_jwt, str))

        # Now we go get the BYO.Pay JWT
        pay_url: str = 'https://staging.byopay.me/api/v1/pay'
        resp = httpx.get(
            f'{pay_url}/auth/external',
            params={
                'token': external_app_jwt,
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data['auth_token'])
        auth_token: str = data['auth_token']
        return auth_token


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
