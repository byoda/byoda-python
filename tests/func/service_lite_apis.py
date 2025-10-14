'''
Test cases for BYO.Tube-lite accounts

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import os
import sys
import yaml
import shutil
import base64
import unittest

from uuid import UUID
from time import sleep
from logging import Logger

from datetime import UTC
from datetime import datetime

from dateutil import parser

from httpx import AsyncClient

from fastapi_limiter import FastAPILimiter

import redis.asyncio as redis

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from byoda.datamodel.network import Network

from byoda.models.data_api_models import PageInfoResponse
from byoda.models.data_api_models import QueryResponseModel

from byoda.secrets.service_secret import ServiceSecret
from byoda.secrets.networkrootca_secret import NetworkRootCaSecret

from byoda.storage.filestorage import FileStorage

from byoda.storage.message_queue import Queue

from byoda.servers.server import Server

from byoda.util.fastapi import setup_api

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.paths import Paths
from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from byotubesvr.models.lite_account import LiteAccountApiModel
from byotubesvr.models.lite_account import LiteAccountSqlModel
from byotubesvr.models.lite_api_models import NetworkLinkResponseModel
from byotubesvr.models.lite_api_models import AssetReactionRequestModel

from byotubesvr.database.network_link_store import NetworkLinkStore
from byotubesvr.database.asset_reaction_store import AssetReactionStore
from byotubesvr.database.settings_store import SettingsStore

from byotubesvr.database.sql import SqlStorage

from byotubesvr.routers import status as StatusRouter
from byotubesvr.routers import account as AccountRouter
from byotubesvr.routers import network_link as NetworkLinkRouter
from byotubesvr.routers import asset_reaction as AssetReactionRouter
from byotubesvr.routers import support as SupportRouter
from byotubesvr.routers import proxy as ProxyRouter
from byotubesvr.routers import settings as SettingsRouter

from byotubesvr.routers.support import EMAIL_SALT
from byotubesvr.routers.support import SUBSCRIPTIONS_FILE

from byoda.util.logger import Logger as ByodaLogger

from tests.lib.util import get_test_uuid

from tests.lib.defines import DATHES_POD_MEMBER_ID
from tests.lib.defines import BYOTUBE_SERVICE_ID

CONFIG_FILE: str = 'config.yml-byotube'

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

        try:
            if os.path.exists(SUBSCRIPTIONS_FILE):
                os.remove(SUBSCRIPTIONS_FILE)
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

        network_link_store = NetworkLinkStore(
            svc_config['svcserver']['lite_store']
        )
        await network_link_store.client.flushall()
        config.network_link_store = network_link_store

        asset_reaction_store = AssetReactionStore(
            svc_config['svcserver']['lite_store']
        )
        await asset_reaction_store.client.flushall()
        config.asset_reaction_store = asset_reaction_store

        settings_store = SettingsStore(
            svc_config['svcserver']['lite_store']
        )
        await settings_store.client.flushall()
        config.settings_store = settings_store

        network_data: dict[str, str] = {
            'root_dir': '/',
            'private_key_password': 'dummy',
        }
        storage_driver: FileStorage = FileStorage('')
        network: Network = Network(network_data, {})
        network.paths = Paths(
            network=config.DEFAULT_NETWORK, root_directory='/'
        )
        root_ca = NetworkRootCaSecret(paths=network.paths)
        root_ca.cert_file = \
            'tests/collateral/network-byoda.net-root-ca-cert.pem'
        await root_ca.load(
            with_private_key=False, storage_driver=storage_driver
        )
        service_secret_data: dict[str, str] = \
            svc_config['svcserver']['proxy_service_secret']
        service_secret = ServiceSecret(BYOTUBE_SERVICE_ID, network)
        service_secret.cert_file = service_secret_data['cert_file']
        service_secret.private_key_file = service_secret_data['key_file']

        await service_secret.load(
            password=service_secret_data['passphrase'],
            storage_driver=storage_driver
        )
        service_secret.save_tmp_private_key()
        config.service_secret = service_secret
        config.server = Server(network)
        config.server.local_storage = storage_driver
        config.server.network.root_ca = root_ca

        config.app = setup_api(
            'Byoda test BYO.Tube-Lite server',
            'server for testing BYO.Tube-Lite APIs', 'v0.0.1',
            [
                StatusRouter,
                AccountRouter,
                SettingsRouter,
                NetworkLinkRouter,
                AssetReactionRouter,
                SupportRouter,
                ProxyRouter,
            ],
            lifespan=None, trace_server=config.trace_server,
        )

        redis_rw_url: str = svc_config['svcserver']['asset_cache_readwrite']
        redis_connection: redis.Redis = redis.from_url(
            redis_rw_url, encoding='utf-8'
        )

        await redis_connection.delete(
            'ratelimits:127.0.0.1:/api/v1/lite/account/signup:6:0',
            'ratelimits:127.0.0.1:/api/v1/lite/account/signup:6:1',
            'queues:email'
        )
        await FastAPILimiter.init(
            redis=redis_connection, prefix='ratelimits'
        )

        config.email_queue = await Queue.setup(redis_rw_url)

        secret: dict[str, str] = svc_config['svcserver']['jwt_asym_secrets'][0]
        with open(secret['cert_file'], 'rb') as file_desc:
            cert: x509.Certificate = x509.load_pem_x509_certificate(
                file_desc.read()
            )
        with open(secret['key_file'], 'rb') as file_desc:
            data: bytes = file_desc.read()
            key: RSAPrivateKey = serialization.load_pem_private_key(
                data, str.encode(secret['passphrase'])
            )
        config.jwt_asym_secrets = [(cert, key)]

        return

    async def asyncTearDown(self) -> None:
        await FastAPILimiter.close()
        await config.email_queue.close()
        await ApiClient.close_all()
        await config.settings_store.close()
        await config.network_link_store.close()
        await config.asset_reaction_store.close()

    async def test_lite_proxy_apis(self) -> None:
        email: str = 'test2@byoda.org'
        password: str = 'test123!'

        async with AsyncClient(app=config.app) as client:
            await self.sign_up(email, password)
            auth_header: dict[str, str] = await self.get_auth_token(
                client, email, password
            )

            self.assertIsNotNone(auth_header)
            base_url: str = 'http://localhost:8000/api/v1/lite/proxy'
            resp: HttpResponse = await client.post(
                f'{base_url}/query', headers=auth_header, json={
                    'data_class': 'public_assets',
                    'remote_member_id': DATHES_POD_MEMBER_ID
                }
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsNotNone(data)
            self.assertTrue(isinstance(data, dict))
            self.assertTrue('total_count' in data)

            resp: HttpResponse = await client.post(
                f'{base_url}/query', headers=auth_header, json={
                    'data_class': 'public_assets',
                    'remote_member_id': DATHES_POD_MEMBER_ID,
                    'after': data['page_info']['end_cursor']
                }
            )
            self.assertEqual(resp.status_code, 200)
            paged_data = resp.json()
            self.assertIsNotNone(paged_data)
            self.assertTrue(isinstance(paged_data, dict))
            self.assertTrue('total_count' in paged_data)

            resp: HttpResponse = await client.post(
                f'{base_url}/query', headers=auth_header, json={
                    'data_class': 'public_assets',
                    'remote_member_id': DATHES_POD_MEMBER_ID,
                    'data_filter': {
                        'ingest_status': {'eq': 'published'}
                    },
                    'after': data['page_info']['end_cursor']
                }
            )
            self.assertEqual(resp.status_code, 200)
            paged_data = resp.json()
            self.assertIsNotNone(paged_data)
            self.assertTrue(isinstance(paged_data, dict))
            self.assertTrue('total_count' in paged_data)

            # Let's switch to the 'messages' data_class, first we
            # query, then we append and then we query again
            data_class = 'messages'
            resp: HttpResponse = await client.post(
                f'{base_url}/query', headers=auth_header, json={
                    'data_class': data_class,
                    'remote_member_id': DATHES_POD_MEMBER_ID,
                }
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsNotNone(data)
            self.assertTrue(isinstance(data, dict))
            self.assertTrue('total_count' in data)

            sender_id: str = str(get_test_uuid())
            message_id: str = str(get_test_uuid())
            resp: HttpResponse = await client.post(
                f'{base_url}/append', headers=auth_header, json={
                    'data_class': data_class,
                    'remote_member_id': DATHES_POD_MEMBER_ID,
                    'data': {
                        'sender_id': sender_id,
                        'message_id': message_id,
                        'created_timestamp': datetime.now(tz=UTC).isoformat(),
                        'contents': 'Test message'

                    }
                }
            )
            self.assertEqual(resp.status_code, 201)

            resp: HttpResponse = await client.post(
                f'{base_url}/query', headers=auth_header, json={
                    'data_class': 'public_assets',
                    'remote_member_id': DATHES_POD_MEMBER_ID,
                    'data_filter': {
                        'message_asset_class': {'eq': 'public_assets'}
                    },
                    'after': data['page_info']['end_cursor']
                }
            )
            self.assertEqual(resp.status_code, 200)
            paged_data = resp.json()
            self.assertIsNotNone(paged_data)
            self.assertTrue(isinstance(paged_data, dict))
            self.assertTrue('total_count' in paged_data)

    async def test_mailinglist_apis(self) -> None:
        test_email_address: str = 'test_mailinglist_apis@test.com'
        listname: str = 'creator-announcements'
        base_url: str = 'http://localhost:8000/api/v1/service/support'
        async with AsyncClient(app=config.app) as client:
            resp: HttpResponse = await client.get(
                f'{base_url}/subscribe', params={
                    'email': test_email_address, 'listname': listname,
                }
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                resp.text.strip('"'), (
                    f'You have subscribed to list {listname} '
                    f'with email address {test_email_address}'
                )
            )

            encoded: str = base64.urlsafe_b64encode(
                f'{EMAIL_SALT}:{test_email_address}'.encode('utf-8')
            ).decode('utf-8')

            resp: HttpResponse = await client.get(
                f'{base_url}/unsubscribe', params={
                    'data': encoded, 'listname': listname,
                }
            )
            self.assertEqual(resp.status_code, 200)
            result: str = resp.text.strip('"')
            self.assertEqual(
                result, (
                    f'You have unsubscribed email address {test_email_address}'
                    f' from list {listname}'
                )
            )
            self.assertTrue(os.path.exists(SUBSCRIPTIONS_FILE))
            with open(SUBSCRIPTIONS_FILE) as file_desc:
                line: str = file_desc.readline()
                action: str
                timestamp: str
                email: str
                incoming_listname: str
                action, timestamp, incoming_listname, email = line.strip(
                ).split(',')
                self.assertEqual(action, 'subscribe')
                self.assertEqual(incoming_listname, listname)
                self.assertEqual(email, test_email_address)
                self.assertTrue(
                    isinstance(datetime.fromisoformat(timestamp), datetime)
                )
                line = file_desc.readline()
                action, timestamp, incoming_listname, email = line.strip(
                ).split(',')
                self.assertEqual(action, 'unsubscribe')
                self.assertEqual(incoming_listname, listname)
                self.assertEqual(email, test_email_address)
                self.assertTrue(
                    isinstance(datetime.fromisoformat(timestamp), datetime)
                )

    async def test_account_failures(self) -> None:
        lite_db: SqlStorage = config.lite_db

        # Email address with uppercase
        with self.assertRaises(ValueError):
            await LiteAccountSqlModel.create(
                'STEVEN@test.com', 'test123!', 'test', lite_db=lite_db
            )

        account_one: LiteAccountSqlModel
        account_two: LiteAccountSqlModel
        # Two accounts with same email
        with self.assertRaises(ValueError):
            account_one = await LiteAccountSqlModel.create(
                'steven@test.com', 'test123!', 'test', lite_db=lite_db
            )
            account_two = await LiteAccountSqlModel.create(
                'steven@test.com', 'test123!', None, lite_db=lite_db
            )

        # Two accounts with same nickname
        account_one.nickname = 'test'
        await account_one.persist()

        with self.assertRaises(ValueError):
            account_two = await LiteAccountSqlModel.create(
                'nottest@test.com', 'test123!', 'test'
            )
            account_two.nickname = 'test'
            await account_two.persist(lite_db=lite_db)

    async def test_account_create(self) -> None:
        lite_db: SqlStorage = config.lite_db

        accounts: list[LiteAccountSqlModel] = []
        count: int
        for count in range(0, 12):
            if count < 10:
                handle: str = f'test-{count}'
            else:
                # We create two accounts with handle is None to make
                # sure Postgres doesn't bark on UNIQUE constraint
                handle = None

            account: LiteAccountSqlModel = await LiteAccountSqlModel.create(
                email=f'test-{count}@test.com', password='test123!',
                handle=handle, lite_db=lite_db
            )
            accounts.append(account)
            self.assertEqual(account.email, f'test-{count}@test.com')

        for count in range(0, 12):
            account: LiteAccountSqlModel = accounts[count]
            account.email = f'modified-test-{count}@test.com'
            await account.persist()

        for count in range(0, 12):
            account = await LiteAccountSqlModel.from_db(
                lite_db, accounts[count].lite_id
            )
            self.assertEqual(account.email, accounts[count].email)

        accounts = await LiteAccountSqlModel.from_db(lite_db)
        self.assertEqual(len(accounts), 12)

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
        model_account: LiteAccountApiModel = \
            LiteAccountSqlModel.from_api_model(model, lite_db)
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

        for count in range(0, 12):
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

            # Make the signup API return the verification_url
            config.test_case = True

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
            verification_url: str | None = data.get('verification_url')
            self.assertIsNotNone(verification_url)

            # Stop making the signup API return the verification_url
            config.test_case = False

            account = await LiteAccountSqlModel.from_db(
                lite_db, UUID(data['lite_id'])
            )
            self.assertIsNone(account.nickname)
            self.assertIsNone(account.is_enabled)
            self.assertFalse(account.is_funded)
            self.assertIsNotNone(account.created_timestamp)
            #
            # Test verification of the email address

            verification_url = verification_url.replace(
                'https://www.byo.tube/verify-email',
                'http://localhost/api/v1/lite/account/verify'
            )
            resp = await client.get(verification_url)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data['status'], 'enabled')

            auth_header: dict[str, str] = await self.get_auth_token(
                client, email, password
            )

            #
            # Get account status
            #
            resp = await client.get(
                f'{BASE_URL}/api/v1/lite/account/status', headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            data: dict[str, str] = resp.json()
            self.assertTrue('status' in data)

            #
            # Try to create another account with same email
            #

            # avoid getting a 429
            sleep(15)
            resp: HttpResponse = await client.post(
                f'{BASE_URL}/api/v1/lite/account/signup',
                json={
                    'email': email, 'password': password,
                }
            )
            self.assertEqual(resp.status_code, 400)
            data = resp.json()
            self.assertEqual(
                data['detail'], f'Account for {email} already exists'
            )

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
                if resp.status_code == 200:
                    data = resp.json()
                    self.assertIsNone(data.get('verification_url'))

            self.assertTrue(429 in responses)

            #
            # Test getting a JWT to authenticate against 3rd-party services
            #
            app_id: UUID = get_test_uuid()
            resp: HttpResponse = await client.post(
                f'{BASE_URL}/api/v1/lite/account/app_token',
                params={'app_id': app_id}, headers=auth_header
            )
            self.assertEqual(resp.status_code, 201)
            data = resp.json()
            self.assertTrue('auth_token' in data)
            self.assertEqual(data['token_type'], 'bearer')
            self.assertEqual(data['app_id'], str(app_id))
            import jwt as py_jwt
            jwt_data: dict = py_jwt.decode(
                data['auth_token'],
                config.jwt_asym_secrets[0][0].public_key(),
                algorithms=['RS256'],
                audience=[f'urn:network-byoda.net:service-16384:app-{app_id}'],
                issuer='urn:network-byoda.net:service-16384',
                options={'require': ['exp', 'iss', 'aud', 'iat', 'lite_id']}
            )
            self.assertIsNotNone(jwt_data)
            self.assertEqual(
                jwt_data['aud'][0],
                f'urn:network-byoda.net:service-16384:app-{app_id}'
            )

            #
            # Test network links
            #
            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/networklinks',
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 404)
            data: dict[str, str] = resp.json()
            self.assertEqual(data.get('detail'), 'No network links found')

            network_link_ids: list[UUID] = []
            links: list[dict[str, any]] = []
            counter: int
            for counter in range(0, 10):
                member_id: UUID = get_test_uuid()
                relation: str = f'friend-{counter}'
                link: dict[str, any] = {
                        'created_timestamp': datetime.now(tz=UTC).timestamp(),
                        'member_id': str(member_id),
                        'relation': relation,
                        'annotations': ['test'],
                    }
                resp: HttpResponse = await client.post(
                    f'{BASE_URL}/api/v1/lite/networklink', json=link,
                    headers=auth_header
                )
                self.assertEqual(resp.status_code, 200)
                network_link_id: UUID = UUID(resp.text.strip('"'))
                network_link_ids.append(network_link_id)
                links.append(link)

            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/networklinks',
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            links_page: dict[str, str] = resp.json()

            query_response: QueryResponseModel = \
                self.parse_network_links_response(links_page)

            self.assertEqual(query_response.total_count, 10)
            self.assertEqual(len(query_response.edges), 10)
            page_info: PageInfoResponse = query_response.page_info
            self.assertFalse(page_info.has_next_page)
            network_link: NetworkLinkResponseModel = \
                query_response.edges[-1].node
            self.assertEqual(
                page_info.end_cursor, network_link.network_link_id
            )

            # Get the membership settings for the Lite account
            settings_url: str = f'{BASE_URL}/api/v1/lite/settings'
            resp: HttpResponse = await client.get(
                f'{settings_url}/member', headers=auth_header
            )
            self.assertEqual(resp.status_code, 404)

            nick: str = 'test_nick'
            show_external_assets: bool = True
            resp: HttpResponse = await client.patch(
                f'{settings_url}/member',
                json={
                    'nick': nick,
                    'show_external_assets': show_external_assets
                },
                headers=auth_header,
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.text.lower(), 'true')

            resp: HttpResponse = await client.get(
                f'{settings_url}/member',
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data['nick'], nick)
            self.assertEqual(
                data['show_external_assets'], show_external_assets
            )

            resp: HttpResponse = await client.patch(
                f'{settings_url}/member',
                json={
                    'nick': nick,
                    'show_external_assets': show_external_assets
                },
                headers=auth_header,
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.text.lower(), 'false')

            # Get a network_link based on member_id
            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/networklinks',
                params={'member_id': query_response.edges[5].node.member_id},
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            links_page: dict[str, str] = resp.json()
            query_response: QueryResponseModel = \
                self.parse_network_links_response(links_page)
            self.assertEqual(query_response.total_count, 1)
            self.assertEqual(len(query_response.edges), 1)
            self.assertEqual(
                query_response.page_info.end_cursor,
                query_response.edges[-1].node.network_link_id
            )

            # Get a network_link based on relation
            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/networklinks',
                params={'relation': 'friend-5'},
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            links_page: dict[str, str] = resp.json()
            query_response: QueryResponseModel = \
                self.parse_network_links_response(links_page)
            self.assertEqual(query_response.total_count, 1)
            self.assertEqual(len(query_response.edges), 1)
            self.assertEqual(
                query_response.page_info.end_cursor,
                query_response.edges[-1].node.network_link_id
            )

            resp: HttpResponse = await client.delete(
                f'{BASE_URL}/api/v1/lite/networklink',
                params={
                    'member_id': str(links[5]['member_id']),
                    'relation': links[5]['relation'],
                    'annotation': links[5]['annotations'][0]

                }, headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.text
            self.assertEqual(int(data), 1)

            #
            # Asset reactions
            #
            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/assetreactions',
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 404)
            data: dict[str, str] = resp.json()
            self.assertEqual(data.get('detail'), 'No asset reactions found')

            member_id = get_test_uuid()
            asset_id: UUID = get_test_uuid()
            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/assetreaction',
                params={'member_id': member_id, 'asset_id': asset_id},
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 404)

            resp: HttpResponse = await client.delete(
                f'{BASE_URL}/api/v1/lite/assetreaction',
                params={'member_id': member_id, 'asset_id': asset_id},
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 404)

            data: dict[str, str] = resp.json()
            self.assertEqual(data.get('detail'), 'No asset reaction found')

            reactions: list[AssetReactionRequestModel] = []
            for count in range(0, 30):
                sleep(0.01)
                asset_reaction: dict[str, any] = {
                    'member_id': str(get_test_uuid()),
                    'asset_id': str(get_test_uuid()),
                    'asset_url': f'http://test.com/{asset_id}',
                    'asset_class': 'public_assets',
                    'relation': f'like-{count}',
                    'bookmark': f'bookmark-{count}',
                    'keywords': ['test'],
                    'annotations': ['test too'],
                    'categories': ['not again'],
                    'list_name': 'favorites'
                }
                resp: HttpResponse = await client.post(
                    f'{BASE_URL}/api/v1/lite/assetreaction',
                    json=asset_reaction, headers=auth_header
                )
                self.assertEqual(resp.status_code, 201)
                reactions.append(asset_reaction)

            index: int = 15
            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/assetreaction',
                params={
                    'member_id': reactions[index]['member_id'],
                    'asset_id': reactions[index]['asset_id']
                },
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            created_timestamp: str = parser.parse(
                data['created_timestamp']
            ).timestamp()

            reactions[index]['relation'] = 'unlike'
            data = resp.json()
            resp: HttpResponse = await client.post(
                f'{BASE_URL}/api/v1/lite/assetreaction',
                json=reactions[index], headers=auth_header
            )
            self.assertEqual(resp.status_code, 201)

            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/assetreaction',
                params={
                    'member_id': reactions[index]['member_id'],
                    'asset_id': reactions[index]['asset_id']
                },
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            new_timestamp: float = parser.parse(
                data['created_timestamp']
            ).timestamp()

            self.assertGreater(new_timestamp, created_timestamp)
            self.assertEqual(data['relation'], 'unlike')

            for count in [0, 3, 9, 12, 19, 23, 29]:
                resp: HttpResponse = await client.delete(
                    f'{BASE_URL}/api/v1/lite/assetreaction',
                    params={
                        'member_id': reactions[count]['member_id'],
                        'asset_id': reactions[count]['asset_id'],
                    }, headers=auth_header
                )
                self.assertEqual(resp.status_code, 204)

            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/assetreactions',
                headers=auth_header
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(
                data['total_count'], AssetReactionStore.DEFAULT_PAGE_SIZE
            )
            self.assertEqual(data['total_count'], len(data['edges']))
            self.assertTrue(data['page_info']['has_next_page'])

            # Modified reaction has updated & newest timestamp is now first
            self.assertEqual(data['edges'][0]['node']['relation'], 'unlike')
            self.assertEqual(data['edges'][1]['node']['relation'], 'like-28')
            self.assertEqual(data['edges'][2]['node']['relation'], 'like-27')
            self.assertEqual(data['edges'][3]['node']['relation'], 'like-26')
            self.assertEqual(data['edges'][4]['node']['relation'], 'like-25')
            self.assertEqual(data['edges'][5]['node']['relation'], 'like-24')
            self.assertEqual(data['edges'][6]['node']['relation'], 'like-22')
            self.assertEqual(data['edges'][7]['node']['relation'], 'like-21')
            self.assertEqual(data['edges'][8]['node']['relation'], 'like-20')
            self.assertEqual(data['edges'][9]['node']['relation'], 'like-18')
            self.assertEqual(data['edges'][10]['node']['relation'], 'like-17')
            self.assertEqual(data['edges'][11]['node']['relation'], 'like-16')
            self.assertEqual(data['edges'][12]['node']['relation'], 'like-14')
            self.assertEqual(data['edges'][13]['node']['relation'], 'like-13')
            self.assertEqual(data['edges'][14]['node']['relation'], 'like-11')
            self.assertEqual(data['edges'][15]['node']['relation'], 'like-10')
            self.assertEqual(data['edges'][16]['node']['relation'], 'like-8')
            self.assertEqual(data['edges'][17]['node']['relation'], 'like-7')
            self.assertEqual(data['edges'][18]['node']['relation'], 'like-6')
            self.assertEqual(data['edges'][19]['node']['relation'], 'like-5')

            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/assetreactions',
                params={'first': AssetReactionStore.MAX_PAGE_SIZE + 1},
                headers=auth_header,
            )
            self.assertEqual(resp.status_code, 400)

            resp: HttpResponse = await client.get(
                f'{BASE_URL}/api/v1/lite/assetreactions',
                params={'first': 0}, headers=auth_header,
            )
            self.assertEqual(resp.status_code, 400)

    def parse_network_links_response(self, data: dict[str, str]
                                     ) -> QueryResponseModel:
        query_response: QueryResponseModel = QueryResponseModel(**data)
        for edge in query_response.edges:
            node_data: dict[str, any] = edge.node
            network_link: NetworkLinkResponseModel = \
                NetworkLinkResponseModel(**node_data)
            edge.node = network_link

        page_info: PageInfoResponse = query_response.page_info
        page_info.end_cursor = UUID(page_info.end_cursor)

        return query_response

    async def sign_up(self, email: str, password: str) -> None:
        # Make the signup API return the verification_url
        config.test_case = True

        lite_db: SqlStorage = config.lite_db

        async with AsyncClient(app=config.app) as client:
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
            verification_url: str | None = data.get('verification_url')
            self.assertIsNotNone(verification_url)

            # Stop making the signup API return the verification_url
            config.test_case = False

            account = await LiteAccountSqlModel.from_db(
                lite_db, UUID(data['lite_id'])
            )
            self.assertIsNone(account.nickname)
            self.assertIsNone(account.is_enabled)
            self.assertFalse(account.is_funded)
            self.assertIsNotNone(account.created_timestamp)
            #
            # Test verification of the email address

            verification_url = verification_url.replace(
                'https://www.byo.tube/verify-email',
                'http://localhost/api/v1/lite/account/verify'
            )
            resp = await client.get(verification_url)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data['status'], 'enabled')

    async def get_auth_token(self, client, email, password) -> dict[str, str]:
        #
        # Get a JWT
        #
        resp: HttpResponse = await client.post(
            f'{BASE_URL}/api/v1/lite/account/auth',
            json={'email': email, 'password': password}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue('auth_token' in data)

        auth_header: dict[str, str] = {
            'Authorization': f'Bearer {data["auth_token"]}'
        }
        return auth_header


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
