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

from byoda.util.fastapi import setup_api

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda import config

from byotubesvr.database.sql import SqlStorage
from byotubesvr.models.lite_account import LiteAccount
from byotubesvr.models.lite_account import LiteModel

from byotubesvr.routers import status as StatusRouter

from tests.lib.setup import get_test_uuid


CONFIG_FILE: str = 'config-byotube.yml'

TEST_DIR: str = '/tmp/byoda-tests/assetdb'

TESTLIST: str = 'testlualist'

TEST_ASSET_ID: UUID = '32af2122-4bab-40bb-99cb-4f696da49e26'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        config_file: str = os.environ.get('CONFIG_FILE', CONFIG_FILE)
        with open(config_file) as file_desc:
            app_config: dict[str, dict[str, any]] = yaml.safe_load(file_desc)

        config.debug = True

        app_config['appserver']['root_dir'] = TEST_DIR

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        if '192.168.' not in app_config['appserver']['asset_cache']:
            raise ValueError(
                'We must be a local Redis server for testing'
            )

        config.trace_server = os.environ.get(
            'TRACE_SERVER', config.trace_server
        )

        sql_db: SqlStorage = await SqlStorage.setup(
            app_config['application']['litedb']
        )
        config.sql_db = sql_db
        for cls in [LiteAccount]:
            await cls.drop_table(sql_db)
            await cls.create_table(sql_db)

        config.app = setup_api(
            'Byoda test BYO.Tube-Lit server',
            'server for testing BYO.Tube-Lite APIs', 'v0.0.1',
            [
                StatusRouter,
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        return

    @classmethod
    async def asyncTearDown(self) -> None:
        await ApiClient.close_all()

    async def test_account_failures(self) -> None:
        sql_db: SqlStorage = config.sql_db

        # Email address with uppercase
        with self.assertRaises(ValueError):
            await LiteAccount.create(
                'STEVEN@test.com', 'test123!', 'test', sql_db=sql_db
            )

        account_one: LiteAccount
        account_two: LiteAccount
        # Two accounts with same handle
        with self.assertRaises(ValueError):
            account_one = await LiteAccount.create(
                'steven@test.com', 'test123!', 'test', sql_db=sql_db
            )
            account_two = await LiteAccount.create(
                'steven@test.com', 'test123!', 'test', sql_db=sql_db
            )

        # Two accounts with same nickname
        account_one.nickname = 'test'
        await account_one.persist()

        with self.assertRaises(ValueError):
            account_two = await LiteAccount.create(
                'steven@test.com', 'test123!', 'test'
            )
            account_two.nickname = 'test'
            await account_two.persist(sql_db=sql_db)

    async def test_account_create(self) -> None:
        sql_db: SqlStorage = config.sql_db

        accounts: list[LiteAccount] = []
        count: int
        for count in range(0, 10):
            account: LiteAccount = await LiteAccount.create(
                email=f'test-{count}@test.com', password='test123!',
                handle=f'test-{count}',
                sql_db=sql_db
            )
            accounts.append(account)
            self.assertEqual(account.email, f'test-{count}@test.com')

        for count in range(0, 10):
            account: LiteAccount = accounts[count]
            account.email = f'modified-test-{count}@test.com'
            await account.persist()

        for count in range(0, 10):
            account = await LiteAccount.from_db(
                sql_db, accounts[count].lite_id
            )
            self.assertEqual(account.email, accounts[count].email)

        accounts = await LiteAccount.from_db(sql_db)
        self.assertEqual(len(accounts), 10)

        # Here we set values for fields NOT included in LiteModel
        accounts[0].is_funded = False
        accounts[0].is_enabled = True
        await accounts[0].persist(all_fields=True)

        # Create an API model, convert it LiteAccount and then upsert
        # an existing record in the DB to see if the previously
        # set values remain unchanged
        model = LiteModel(
            lite_id=accounts[0].lite_id, email=accounts[0].email,
            password='test123!', handle='testmodel', nickname='test'
        )
        model_account: LiteAccount = LiteAccount.from_api_model(model, sql_db)
        await model_account.persist(all_fields=False)

        account = await LiteAccount.from_db(sql_db, accounts[0].lite_id)
        self.assertEqual(account.is_funded, False)
        self.assertEqual(account.is_enabled, True)
        self.assertEqual(account.nickname, 'test')

        for count in range(0, 10):
            account = accounts[count]
            await account.delete()

        accounts = await LiteAccount.from_db(sql_db)
        self.assertEqual(len(accounts), 0)

    async def test_service_auth_api(self) -> None:
        BASE_URL: str = 'http://localhost:8000'
        AUTH_URL: str = f'{BASE_URL}/auth'

        async with AsyncClient(app=config.app) as client:
            resp: HttpResponse = await client.get(
                'http://localhost:8000/api/v1/status'
            )
            self.assertEqual(resp.status_code, 200)


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
