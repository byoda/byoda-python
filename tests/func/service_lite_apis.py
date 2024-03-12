'''
Test cases for BYO.Yube-lite accounts

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import os
import sys
import yaml
import shutil
import unittest

from uuid import UUID

from httpx import AsyncClient

from fastapi_limiter import FastAPILimiter

import redis.asyncio as redis

from byoda.storage.message_queue import Queue

from byoda.util.fastapi import setup_api

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda import config

from byotubesvr.database.sql import SqlStorage
from byotubesvr.models.lite_account import LiteAccountApiModel
from byotubesvr.models.lite_account import LiteAccountSqlModel

from byotubesvr.routers import status as StatusRouter
from byotubesvr.routers import account as AccountRouter


CONFIG_FILE: str = 'config-byotube.yml'

BASE_URL: str = 'http://localhost:8000'

TEST_DIR: str = '/tmp/byoda-tests/service_lite_apis'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        config_file: str = os.environ.get('CONFIG_FILE', CONFIG_FILE)
        with open(config_file) as file_desc:
            svc_config: dict[str, dict[str, any]] = yaml.safe_load(file_desc)

        config.debug = True

        svc_config['svcserver']['root_dir'] = TEST_DIR

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        if '192.168.' not in svc_config['svcserver']['litedb']:
            raise ValueError(
                'We must use a local Postgres server for testing'
            )
        if '192.168.' not in svc_config['svcserver']['asset_cache_readwrite']:
            raise ValueError(
                'We must use a local Redis server for testing'
            )

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        config.jwt_secrets = svc_config['svcserver']['jwt_secrets']

        lite_db: SqlStorage = await SqlStorage.setup(
            svc_config['svcserver']['litedb']
        )

        config.lite_db = lite_db
        for cls in [LiteAccountSqlModel]:
            await cls.drop_table(lite_db)
            await cls.create_table(lite_db)

        config.app = setup_api(
            'Byoda test BYO.Tube-Lite server',
            'server for testing BYO.Tube-Lite APIs', 'v0.0.1',
            [
                StatusRouter,
                AccountRouter,
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        redis_rw_url: str = svc_config['svcserver']['asset_cache_readwrite']
        redis_connection = redis.from_url(redis_rw_url, encoding='utf-8')

        await redis_connection.delete(
            'ratelimits:127.0.0.1:/api/v1/lite/account/signup:6:0',
            'ratelimits:127.0.0.1:/api/v1/lite/account/signup:6:1',
            'queues:email'
        )
        await FastAPILimiter.init(
            redis=redis_connection, prefix='ratelimits'
        )

        config.email_queue = await Queue.setup(redis_rw_url)
        return

    async def asyncTearDown(self) -> None:
        await FastAPILimiter.close()
        await config.email_queue.close()
        await ApiClient.close_all()

    async def test_account_failures(self) -> None:
        lite_db: SqlStorage = config.lite_db

        # Email address with uppercase
        with self.assertRaises(ValueError):
            await LiteAccountSqlModel.create(
                'STEVEN@test.com', 'test123!', 'test', lite_db=lite_db
            )

        account_one: LiteAccountSqlModel
        account_two: LiteAccountSqlModel
        # Two accounts with same handle
        with self.assertRaises(ValueError):
            account_one = await LiteAccountSqlModel.create(
                'steven@test.com', 'test123!', 'test', lite_db=lite_db
            )
            account_two = await LiteAccountSqlModel.create(
                'steven@test.com', 'test123!', 'test', lite_db=lite_db
            )

        # Two accounts with same nickname
        account_one.nickname = 'test'
        await account_one.persist()

        with self.assertRaises(ValueError):
            account_two = await LiteAccountSqlModel.create(
                'steven@test.com', 'test123!', 'test'
            )
            account_two.nickname = 'test'
            await account_two.persist(lite_db=lite_db)

    async def test_account_create(self) -> None:
        lite_db: SqlStorage = config.lite_db

        accounts: list[LiteAccountSqlModel] = []
        count: int
        for count in range(0, 10):
            account: LiteAccountSqlModel = await LiteAccountSqlModel.create(
                email=f'test-{count}@test.com', password='test123!',
                handle=f'test-{count}',
                lite_db=lite_db
            )
            accounts.append(account)
            self.assertEqual(account.email, f'test-{count}@test.com')

        for count in range(0, 10):
            account: LiteAccountSqlModel = accounts[count]
            account.email = f'modified-test-{count}@test.com'
            await account.persist()

        for count in range(0, 10):
            account = await LiteAccountSqlModel.from_db(
                lite_db, accounts[count].lite_id
            )
            self.assertEqual(account.email, accounts[count].email)

        accounts = await LiteAccountSqlModel.from_db(lite_db)
        self.assertEqual(len(accounts), 10)

        # Here we set values for fields NOT included in LiteModel
        accounts[0].is_funded = False
        accounts[0].is_enabled = True
        await accounts[0].persist(all_fields=True)

        # Create an API model, convert it LiteAccountSqlModel and then upsert
        # an existing record in the DB to see if the previously
        # set values remain unchanged
        model = LiteAccountApiModel(
            email=accounts[0].email, password='test123!', handle='testmodel',
            nickname='test'
        )
        model_account = LiteAccountSqlModel.from_api_model(model, lite_db)
        model_account.lite_id = accounts[0].lite_id
        await model_account.persist(all_fields=False)

        account = await LiteAccountSqlModel.from_db(
            lite_db, accounts[0].lite_id
        )
        self.assertEqual(account.is_funded, False)
        self.assertEqual(account.is_enabled, True)
        self.assertEqual(account.nickname, None)
        self.assertIsNotNone(account.created_timestamp)

        response = LiteAccountSqlModel.from_api_model(model)
        self.assertEqual(response.email, model.email)
        self.assertEqual(response.email, accounts[0].email)

        for count in range(0, 10):
            account = accounts[count]
            await account.delete()

        accounts = await LiteAccountSqlModel.from_db(lite_db)
        self.assertEqual(len(accounts), 0)

    async def test_account_signup_api(self) -> None:
        lite_db: SqlStorage = config.lite_db

        async with AsyncClient(app=config.app) as client:
            resp: HttpResponse = await client.get(
                'http://localhost:8000/api/v1/status'
            )
            self.assertEqual(resp.status_code, 200)

            #
            # Test signup
            #
            email: str = 'test@byoda.org'
            password: str = 'test123!'
            resp: HttpResponse = await client.post(
                f'{BASE_URL}/api/v1/lite/account/signup',
                json={
                    'email': email, 'password': password,
                    'handle': 'testhandle'
                }
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue('lite_id' in data)
            self.assertEqual(data['email'], email)
            verification_url = data.get('verification_url')
            self.assertIsNotNone(verification_url)

            account = await LiteAccountSqlModel.from_db(
                lite_db, UUID(data['lite_id'])
            )
            self.assertIsNone(account.nickname)
            self.assertIsNone(account.is_enabled)
            self.assertIsNone(account.is_funded)
            self.assertIsNotNone(account.created_timestamp)

            #
            # Test verification of the email address
            #
            resp = await client.get(verification_url)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data['status'], 'enabled')

            #
            # Get a JWT
            #
            resp = await client.post(
                f'{BASE_URL}/api/v1/lite/account/auth',
                json={'email': email, 'password': password}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue('auth_token' in data)

            auth_header: dict[str, str] = {
                'Authorization': f'Bearer {data["auth_token"]}'
            }
            #
            # Get account status
            #
            resp = await client.get(
                f'{BASE_URL}/api/v1/lite/account/status', headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue('status' in data)


            #
            # Test rate limiter
            #
            responses: list[int] = []
            for counter in range(0, 5):
                resp: HttpResponse = await client.post(
                    f'{BASE_URL}/api/v1/lite/account/signup',
                    json={
                        'email': f'test-ratelimit-{counter}@test.com',
                        'password': 'test123!',
                        'handle': f'testhandle-rate-limit-{counter}'
                    }
                )
                responses.append(resp.status_code)

            self.assertTrue(429 in responses)


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
