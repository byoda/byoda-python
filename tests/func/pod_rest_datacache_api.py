#!/usr/bin/env python3

'''
Test the POD REST and GraphQL APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import sys
import unittest

from uuid import UUID
from datetime import datetime
from datetime import timezone
from fastapi import FastAPI

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.sqltable import SqlTable
from byoda.datamodel.dataclass import SchemaDataItem
from byoda.datamodel.datafilter import DataFilterSet

from byoda.datamodel.sqltable import META_ID_COLUMN
from byoda.datamodel.sqltable import META_ID_TYPE_COLUMN
from byoda.datamodel.sqltable import CACHE_EXPIRE_COLUMN
from byoda.datamodel.sqltable import CACHE_ORIGIN_CLASS_COLUMN

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType
from byoda.datatypes import DataFilterType
from byoda.datamodel.table import QueryResult

from byoda.datastore.cache_store import CacheStore

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.data_api_client import DataApiClient
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

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import AZURE_POD_ADDRESS_BOOK_PUBLIC_ASSETS_ASSET_ID

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK

TEST_DIR = '/tmp/byoda-tests/datacache'

APP: FastAPI | None = None


class TestRestDataCacheApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR)
        network_data: dict[str, str] = await setup_network(delete_tmp_dir=True)

        config.test_case = "TEST_CLIENT"
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
        await DataApiClient.close_all()

    async def test_datacache_api_jwt(self):
        account: Account = config.server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member: Member = await account.get_membership(service_id)
        password: str = os.environ['ACCOUNT_SECRET']

        data: dict[str, str] = {
            'username': str(member.member_id)[:8],
            'password': password,
            'target_type': IdType.MEMBER.value,
            'service_id': ADDRESSBOOK_SERVICE_ID
        }
        url: str = f'{BASE_URL}/v1/pod/authtoken'
        resp: HttpResponse = await ApiClient.call(
            url, method=HttpMethod.POST, data=data, app=APP
        )

        self.assertEqual(resp.status_code, 200)
        result: dict[str, str] = resp.json()
        auth_header = {
            'Authorization': f'bearer {result["auth_token"]}'
        }

        class_name: str = 'incoming_assets'
        # Test an object
        url = BASE_URL + f'/v1/data/service-{service_id}'

        server: PodServer = config.server
        cache_store: CacheStore = server.cache_store

        sql_table: SqlTable = cache_store.get_table(
            member.member_id, class_name
        )

        #
        # Add an object to the cache_store
        #
        asset_id: UUID = AZURE_POD_ADDRESS_BOOK_PUBLIC_ASSETS_ASSET_ID
        now: str = str(datetime.now(tz=timezone.utc).isoformat())
        vars: dict[str, str | UUID] = {
            'data': {
                'asset_id': asset_id,
                'asset_type': 'video',
                'created_timestamp': now,
            }
        }

        # This API call does not set 'origin_class_name' as that
        # only gets set when calling Memberdata.append() directly
        resp: HttpResponse = await DataApiClient.call(
            service_id=service_id, class_name=class_name,
            action=DataRequestType.APPEND, data=vars, headers=auth_header,
            app=APP
        )
        self.assertEqual(resp.status_code, 200)

        data: dict[str, dict[str, str | UUID | datetime]] = resp.json()
        self.assertEqual(data, 1)

        stmt: str = (
            'SELECT expires, id, id_type, origin_class_name '
            'FROM _incoming_assets'
        )
        result = await sql_table.sql_store.execute(
            stmt, member_id=member.member_id, fetchall=True,
        )
        row = result[0]
        expiration: list[float] = [row[CACHE_EXPIRE_COLUMN]]
        origin_id: UUID = row[META_ID_COLUMN]
        origin_id_type: IdType = row[META_ID_TYPE_COLUMN]
        origin_class_name: str = row[CACHE_ORIGIN_CLASS_COLUMN]
        self.assertIsNotNone(expiration)
        self.assertIsNotNone(origin_id)
        self.assertIsNotNone(origin_id_type)
        self.assertIsNone(origin_class_name)

        #
        # Confirm the object is in the cache store
        #
        data_filter: DataFilterType = {
            'asset_id': {'eq': asset_id}
        }
        resp: HttpResponse = await DataApiClient.call(
            service_id=service_id, class_name=class_name,
            action=DataRequestType.QUERY, data_filter=data_filter,
            headers=auth_header, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data['total_count'], 1)
        edges: list[object] = data['edges']
        self.assertEqual(edges[0]['node']['asset_id'], str(asset_id))

        result = await sql_table.sql_store.execute(
            f'SELECT expires FROM _{class_name}',
            member_id=member.member_id, fetchall=True,
        )
        expiration.append(result[0][CACHE_EXPIRE_COLUMN])
        self.assertEqual(
            expiration[0], expiration[1],
            'Expire value should not change from a query'
        )

        #
        # Update the object in the cache store
        #
        data_filter: DataFilterType = {
            'asset_id': {'eq': asset_id}
        }
        data: dict[str, str] = {
            'data': {
                'asset_id': asset_id,
                'asset_type': 'video',
                'created_timestamp': str(
                    datetime.now(tz=timezone.utc).isoformat()
                ),
            }
        }
        resp: HttpResponse = await DataApiClient.call(
            service_id=service_id, class_name=class_name,
            action=DataRequestType.UPDATE, data_filter=data_filter,
            data=data, headers=auth_header, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data: dict[str, str | UUID | datetime] = resp.json()
        self.assertIsNotNone(data)
        self.assertEqual(data, 1)

        result = await sql_table.sql_store.execute(
            f'SELECT expires FROM _{class_name}',
            member_id=member.member_id, fetchall=True,
        )
        expiration.append(result[0][CACHE_EXPIRE_COLUMN])
        self.assertNotEqual(
            expiration[1], expiration[2],
            'Expire value should change after an update'
        )

        #
        # Confirm the object in the cache store was updated
        #
        data_filter: DataFilterType = {
            'asset_id': {'eq': asset_id}
        }
        resp: HttpResponse = await DataApiClient.call(
            service_id=service_id, class_name=class_name,
            action=DataRequestType.QUERY, data_filter=data_filter,
            headers=auth_header, app=APP
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data['total_count'], 1)
        edges: list[object] = data['edges']
        self.assertEqual(edges[0]['node']['asset_id'], str(asset_id))
        self.assertEqual(edges[0]['node']['asset_type'], 'video')
        self.assertNotEqual(edges[0]['node']['created_timestamp'], now)

        #
        # Claim that the data in the cache was sourced from the Azure pod
        # and needs to be refreshed and then refresh the cached asset
        #
        expiration.append(result[0][CACHE_EXPIRE_COLUMN])
        now: float = datetime.now(tz=timezone.utc).timestamp()
        refresh_timestamp: float = now + 100

        azure_asset_timestamp: float = 1696909415.03106
        result = await sql_table.sql_store.execute(
            'UPDATE _incoming_assets '
            'SET origin_class_name = "public_assets", '
            f'id = "{AZURE_POD_MEMBER_ID}", '
            f'id_type = "members-", expires = {refresh_timestamp}, '
            f'_created_timestamp = {azure_asset_timestamp} '
            f'WHERE _asset_id = "{asset_id}"',
            member_id=member.member_id
        )
        self.assertEqual(result.rowcount, 1)

        data_class: SchemaDataItem = member.get_data_class(class_name)
        row_count = await cache_store.refresh_table(
            server, member, data_class, refresh_timestamp
        )
        self.assertEqual(row_count, 1)

        sql_table: SqlTable = cache_store.get_table(
            member.member_id, 'incoming_assets'
        )
        data_filter_set = DataFilterSet(
            {'asset_id': {'eq': asset_id}}, data_class=data_class
        )
        data: list[QueryResult] = await sql_table.query(
            data_filters=data_filter_set
        )
        self.assertEqual(len(data), 1)
        _, asset_meta = data[0]
        self.assertGreater(asset_meta['expires'], refresh_timestamp)

        #
        # Purge the cache and confirm the object has been deleted
        #
        expire_timestamp: float = now + 7 * 24 * 60 * 60
        rows = await cache_store.expire_table(
            server, member, data_class, expire_timestamp
        )
        self.assertEqual(rows, 1)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
