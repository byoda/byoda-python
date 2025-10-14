#!/usr/bin/env python3

'''
Test the POD REST and Data APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license
'''

import os
import sys
import unittest

from uuid import UUID
from logging import Logger

from datetime import datetime
from datetime import timezone, timedelta

import httpx

from fastapi import FastAPI

from yaml import safe_load as yaml_safe_loader

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.content_key import RESTRICTED_CONTENT_KEYS_TABLE
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.table import Table
from byoda.datamodel.monetization import Monetizations

from byoda.datatypes import IdType
from byoda.datatypes import MonetizationType

from byoda.storage.postgres import PostgresStorage

from byoda.datastore.data_store import DataStore

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.util.fastapi import setup_api

from byoda.exceptions import ByodaRuntimeError

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter
from podserver.routers import accountdata as AccountDataRouter
from podserver.routers import content_token as ContentTokenRouter

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account

from tests.lib.defines import BYOTUBE_SERVICE_ID
from tests.lib.defines import BYOTUBE_VERSION

from tests.lib.util import get_test_uuid

TEST_DIR: str = '/tmp/byoda-tests/content-token'
TEST_FILE: str = TEST_DIR + '/content_keys.json'

APP: FastAPI | None = None

BASE_URL: str = 'http://localhost:8000/api/v1/pod'


class TestDirectoryApis(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR)
        network_data: dict[str, str] = await setup_network(delete_tmp_dir=True)

        config.test_case = "TEST_CLIENT"
        config.disable_pubsub = True

        server: PodServer = config.server

        # test_config: dict[str, str | int] = self.get_byopay_data()
        account: Account = await setup_account(
            network_data, test_dir=TEST_DIR, clean_pubsub=False,
            service_id=BYOTUBE_SERVICE_ID, version=BYOTUBE_VERSION,
            # member_id=test_config['member_id']
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
        member: Member = await account.get_membership(BYOTUBE_SERVICE_ID)

        data_store: DataStore = config.server.data_store
        key_table: Table = data_store.get_table(
            member.member_id, RESTRICTED_CONTENT_KEYS_TABLE
        )

        config.server.whitelist_dir = TEST_DIR

        key_id: int = 99999999
        data: dict[str, str | datetime] = {
            'key_id': key_id,
            'key': 'somesillykey',
            'not_after': datetime.now(tz=timezone.utc) + timedelta(days=1),
            'not_before': datetime.now(tz=timezone.utc) - timedelta(days=1)
        }

        cursor: str = Table.get_cursor_hash(data, None, list(data.keys()))
        await key_table.append(
            data, cursor, origin_id=None, origin_id_type=None,
            origin_class_name=None
        )

        monetizations: list[dict[str, any]] | None = None
        await self.monetization_test(member.member_id, monetizations)

        monetizations = []
        await self.monetization_test(member.member_id, monetizations)

        monetizations = Monetizations.from_dict(
            [
                {'monetization_type': MonetizationType.FREE}
            ]
        )
        await self.monetization_test(member.member_id, monetizations)

        monetizations = Monetizations.from_dict(
            [
                {'monetization_type': MonetizationType.SUBSCRIPTION}
            ]
        )
        await self.monetization_test(
            member.member_id, monetizations, expect_success=False
        )

        monetizations = Monetizations.from_dict(
            [
                {'monetization_type': MonetizationType.SUBSCRIPTION},
                {'monetization_type': MonetizationType.FREE}
            ]
        )

        await self.monetization_test(
            member.member_id, monetizations, expect_success=True
        )

        monetizations = Monetizations.from_dict(
            [
                {'monetization_type': MonetizationType.BURSTPOINTS},
            ]
        )
        await self.monetization_test(
            member.member_id, monetizations, attest=None, expect_success=False
        )

        attest: dict[str, any] = await self.get_attestation()
        monetizations = Monetizations.from_dict(
            [
                {'monetization_type': MonetizationType.BURSTPOINTS},
            ]
        )
        await self.monetization_test(
            member.member_id, monetizations, attest=attest,
            expect_success=True
        )
        await key_table.delete(
            DataFilterSet({'key_id': {'eq': key_id}}),
            placeholder_function=PostgresStorage.get_named_placeholder

        )

    async def monetization_test(self, member_id: UUID,
                                monetizations: Monetizations | None,
                                attest: dict[str, any] | None = None,
                                expect_success: bool = True) -> None:
        '''
        Test getting a content token with an asset using the provided
        monetization requirements
        '''

        data_store: DataStore = config.server.data_store

        asset_table: Table = data_store.get_table(
            member_id, 'public_assets'
        )

        asset_id: UUID = get_test_uuid()

        mon_count: int
        if not monetizations:
            mon_count = None
        else:
            mon_count = len(monetizations)

        _LOGGER.debug(f'Creating test asset with {mon_count} monetizations')

        monetization_data: list[dict[str, any]] | None = \
            monetizations.as_dict() if monetizations else None

        asset: dict[str, any] = {
            'asset_id': str(asset_id),
            'title': f'Test asset with {mon_count} monetizations',
            'asset_type': 'video',
            'monetizations': monetization_data
        }
        await asset_table.append(
            asset, cursor='blah', origin_id=get_test_uuid(),
            origin_id_type=IdType.MEMBER, origin_class_name=None
        )

        url: str = BASE_URL + '/content/token'
        data: dict[str, str] = {
            'service_id': BYOTUBE_SERVICE_ID,
            'asset_id': str(asset_id),
            'member_id': str(member_id),
            'member_id_type': IdType.MEMBER.value,
        }
        if attest:
            data['attestation'] = attest
            data['member_id'] = attest['member_id']

        try:
            resp: HttpResponse = await ApiClient.call(
                url,  method=HttpMethod.POST, data=data, app=APP
            )
            if expect_success:
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertTrue('content_token' in data)
                self.assertTrue('key_id' in data)
        except ByodaRuntimeError:
            if expect_success:
                raise

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
            test_config: dict[str, any] = yaml_safe_loader(file_desc)

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
        self.assertIsInstance(account_jwt, str)
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
        self.assertIsInstance(member_jwt, str)
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
        self.assertIsInstance(external_app_jwt, str)

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


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
