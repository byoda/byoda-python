#!/usr/bin/env python3

'''
Test the POD REST and GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import unittest

from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta

import orjson
import requests

from byoda.datamodel.account import Account
from byoda.datamodel.network import Network
from byoda.datamodel.content_key import ContentKey
from byoda.datamodel.content_key import ContentKeyStatus
from byoda.datamodel.content_key import RESTRICTED_CONTENT_KEYS_TABLE
from byoda.datamodel.datafilter import DataFilterSet

from byoda.datastore.data_store import DataStore
from byoda.datastore.data_store import DataStoreType

from byoda.util.api_client.graphql_client import GraphQlClient

from byoda.util.logger import Logger
from byoda.util.fastapi import setup_api

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import get_account_id

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

# Settings must match config.yml used by directory server
NETWORK: str = config.DEFAULT_NETWORK

TEST_DIR: str = '/tmp/byoda-tests/podserver'
TEST_FILE: str = TEST_DIR + '/content_keys.json'


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network(delete_tmp_dir=False)

        config.test_case = "TEST_CLIENT"

        network: Network = config.server.network
        server = config.server

        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=server.HTTP_PORT)

        network_data['account_id'] = get_account_id(network_data)

        account = Account(network_data['account_id'], network)
        account.password = network_data.get('account_secret')
        await account.load_secrets()

        server.account = account

        await config.server.set_data_store(
            DataStoreType.SQLITE, account.data_secret
        )

        await server.get_registered_services()

        app = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1', [account.tls_secret.common_name], [
                AccountRouter, MemberRouter, AuthTokenRouter,
                AccountDataRouter
            ]
        )

        for account_member in account.memberships.values():
            account_member.enable_graphql_api(app)

    @classmethod
    async def asyncTearDown(self):
        await GraphQlClient.close_all()

    async def test_restricted_content_key_api(self):
        pod_account = config.server.account
        await pod_account.load_memberships()
        member = pod_account.memberships.get(ADDRESSBOOK_SERVICE_ID)

        data_store: DataStore = config.server.data_store
        key_table = data_store.get_table(
            member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )

        key_id: int = 99999999
        await key_table.append(
            {
                'key_id': key_id,
                'key': 'somesillykey',
                'not_after': datetime.now(tz=timezone.utc) + timedelta(days=1),
                'not_before': datetime.now(tz=timezone.utc) - timedelta(days=1)
            }
        )

        url = BASE_URL + '/v1/pod/content/token'
        asset_id = uuid4()
        query_params = {
            'asset_id': str(asset_id),
            'service_id': ADDRESSBOOK_SERVICE_ID,
            'class_name': 'public_assets',
            'signedby': str(uuid4()),
            'token': 'placeholder'
        }
        result = requests.get(url, params=query_params)
        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertTrue('content_token' in data)

        await key_table.delete(DataFilterSet({'key_id': {'eq': key_id}}))

    async def test_restricted_content_keys_file(self):
        keys: list[ContentKey] = []
        content_key = await ContentKey.create(
            key=uuid4(), key_id=1, not_before=None, not_after=None,
        )
        keys.append(content_key.as_dict())
        content_key = await ContentKey.create(
            key=uuid4(), key_id=2,
            not_before=datetime.now(tz=timezone.utc) - timedelta(weeks=52),
            not_after=datetime.now(tz=timezone.utc) + timedelta(weeks=520),
        )
        keys.append(content_key.as_dict())
        content_key = await ContentKey.create(
            key=uuid4(), key_id=5,
            not_before=datetime.now(tz=timezone.utc) - timedelta(days=1),
            not_after=datetime.now(tz=timezone.utc) + timedelta(weeks=1),
        )
        keys.append(content_key.as_dict())
        content_key = await ContentKey.create(
            key=uuid4(), key_id=6,
            not_before=datetime.now(tz=timezone.utc) - timedelta(days=2),
            not_after=datetime.now(tz=timezone.utc) - timedelta(days=1),
        )
        keys.append(content_key.as_dict())

        key_data = orjson.dumps(keys, option=orjson.OPT_SERIALIZE_UUID)
        with open(TEST_FILE, 'w') as file_desc:
            file_desc.write(key_data.decode('utf-8'))

        keys = await ContentKey.get_content_keys(filepath=TEST_FILE)
        self.assertEqual(len(keys), 4)

        keys = await ContentKey.get_content_keys(
            filepath=TEST_FILE, status=ContentKeyStatus.ACTIVE
        )
        self.assertEqual(len(keys), 2)

        keys = await ContentKey.get_content_keys(
            filepath=TEST_FILE, status=ContentKeyStatus.INACTIVE
        )
        self.assertEqual(len(keys), 1)

        keys = await ContentKey.get_content_keys(
            filepath=TEST_FILE, status=ContentKeyStatus.EXPIRED
        )
        self.assertEqual(len(keys), 1)

        content_key = await ContentKey.get_active_content_key(
            filepath=TEST_FILE
        )
        self.assertIsNotNone(content_key)
        self.assertEqual(content_key.key_id, 5)

    async def test_restricted_content_keys_table(self):
        pod_account = config.server.account
        await pod_account.load_memberships()
        account_member = pod_account.memberships.get(ADDRESSBOOK_SERVICE_ID)

        data_store: DataStore = config.server.data_store
        table = data_store.get_table(
            account_member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )

        await table.delete(data_filters={})
        content_key = await ContentKey.create(
            key=uuid4(), key_id=None, not_before=None, not_after=None,
            table=table
        )

        await content_key.persist(table)

        keys = await ContentKey.get_content_keys(table=table)
        self.assertEqual(len(keys), 1)

        content_key = await ContentKey.create(
            key=uuid4(), key_id=5,
            not_before=datetime.now(tz=timezone.utc) - timedelta(weeks=52),
            not_after=datetime.now(tz=timezone.utc) + timedelta(weeks=520),
            table=table
        )

        key_id = content_key.key_id
        await content_key.persist(table)
        keys = await ContentKey.get_content_keys(table=table)
        self.assertEqual(len(keys), 2)

        keys = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.INACTIVE
        )
        self.assertEqual(len(keys), 1)

        keys = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.EXPIRED
        )
        self.assertEqual(len(keys), 0)

        keys = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.ACTIVE
        )
        self.assertEqual(len(keys), 1)

        content_key = await ContentKey.get_active_content_key(table=table)
        self.assertIsNotNone(content_key)
        self.assertEqual(key_id, content_key.key_id)

        content_key = await ContentKey.create(
            key=uuid4(), key_id=None,
            not_before=datetime.now(tz=timezone.utc) - timedelta(days=1),
            not_after=datetime.now(tz=timezone.utc) + timedelta(weeks=1),
            table=table
        )
        self.assertEqual(content_key.key_id, key_id + 1)
        key_id = content_key.key_id
        await content_key.persist()

        keys = await ContentKey.get_content_keys(table=table)
        self.assertEqual(len(keys), 3)

        keys = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.ACTIVE
        )
        self.assertEqual(len(keys), 2)

        keys = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.INACTIVE
        )
        self.assertEqual(len(keys), 1)

        keys = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.EXPIRED
        )
        self.assertEqual(len(keys), 0)

        content_key = await ContentKey.get_active_content_key(table=table)
        self.assertIsNotNone(content_key)
        self.assertEqual(key_id, content_key.key_id)

        content_key = await ContentKey.create(
            key=uuid4(), key_id=None,
            not_before=datetime.now(tz=timezone.utc) - timedelta(days=2),
            not_after=datetime.now(tz=timezone.utc) - timedelta(days=1),
            table=table
        )

        await content_key.persist()

        keys = await ContentKey.get_content_keys(table=table)
        self.assertEqual(len(keys), 4)

        keys = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.ACTIVE
        )
        self.assertEqual(len(keys), 2)

        keys = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.INACTIVE
        )
        self.assertEqual(len(keys), 1)

        keys = await ContentKey.get_content_keys(
            table=table, status=ContentKeyStatus.EXPIRED
        )
        self.assertEqual(len(keys), 1)

        content_key = await ContentKey.get_active_content_key(table=table)
        self.assertIsNotNone(content_key)
        self.assertEqual(key_id, content_key.key_id)

    async def test_restricted_content_token(self):
        pod_account = config.server.account
        await pod_account.load_memberships()
        service_id = ADDRESSBOOK_SERVICE_ID
        member = pod_account.memberships.get(service_id)

        data_store: DataStore = config.server.data_store
        table = data_store.get_table(
            member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )

        await table.delete(data_filters={})

        content_key = await ContentKey.create(
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

        url = BASE_URL + '/v1/pod/content/asset'
        result = requests.get(
            url, headers={
                'Authorization': f'Bearer {token}',
                'original-url': f'/restricted/{asset_id}/some-asset.file'
            },
            params={
                'key_id': content_key.key_id,
                'service_id': service_id,
                'member_id': member.member_id,
                'asset_id': asset_id,
            }
        )
        self.assertEqual(result.status_code, 200)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
