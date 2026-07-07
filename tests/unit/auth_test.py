#!/usr/bin/env python3

'''
Test cases for authentication of REST / Data API calls

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest

from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4
from logging import Logger

from cryptography.hazmat.primitives.asymmetric.dsa import DSAPublicKey
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PublicKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x448 import X448PublicKey
import jwt as py_jwt

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography import x509

from fastapi import HTTPException

from byoda.requestauth.requestauth import RequestAuth

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.member import Secret
from byoda.secrets.networkrootca_secret import NetworkRootCaSecret
from byoda.secrets.networkservicesca_secret import NetworkServicesCaSecret
from byoda.secrets.serviceca_secret import ServiceCaSecret
from byoda.secrets.service_secret import ServiceSecret
from byoda.secrets.membersca_secret import MembersCaSecret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.appsca_secret import AppsCaSecret
from byoda.secrets.app_secret import AppSecret

from byoda.servers.pod_server import PodServer

from byoda.datatypes import CloudType
from byoda.datatypes import IdType
from byoda.datatypes import ServerType
from byoda.datatypes import TlsStatus

from byoda.requestauth.jwt import JWT

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpMethod
from byoda.util.paths import Paths

from byoda.util.logger import Logger as ByodaLogger

from byoda.storage.filestorage import FileStorage

from byoda import config

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import PASSWORD
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID


CONFIG_FILE = 'tests/collateral/config.yml'

TEST_DIR = '/tmp/byoda-tests/auth'
NETWORK = 'test.net'
TARGET_SERVICE_ID = 2222
ROGUE_SERVICE_ID = 1111


def _escaped_cert(secret: Secret) -> str:
    return quote(secret.cert_as_pem().decode('utf-8'), safe='')


class TestMTlsCertChain(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        shutil.rmtree(TEST_DIR, ignore_errors=True)
        os.makedirs(TEST_DIR, exist_ok=True)

        storage = FileStorage(TEST_DIR, CloudType.LOCAL)
        self.paths = Paths(
            network=NETWORK, root_directory=TEST_DIR, account='pod',
            storage_driver=storage,
        )
        self.network = SimpleNamespace(name=NETWORK, paths=self.paths)

        self.root_ca = NetworkRootCaSecret(paths=self.paths)
        await self.root_ca.create()

        self.services_ca = NetworkServicesCaSecret(self.paths)
        services_ca_csr = await self.services_ca.create_csr()
        self.services_ca.from_signed_cert(
            self.root_ca.sign_csr(services_ca_csr)
        )

        (
            self.target_service_ca,
            self.target_members_ca,
            self.target_apps_ca,
        ) = \
            await self._create_service_branch(TARGET_SERVICE_ID)
        (
            self.rogue_service_ca,
            self.rogue_members_ca,
            self.rogue_apps_ca,
        ) = \
            await self._create_service_branch(ROGUE_SERVICE_ID)

        local_member = await self._create_member_secret(
            self.target_members_ca, TARGET_SERVICE_ID
        )

        service = SimpleNamespace(apps_ca=self.target_apps_ca)
        membership = SimpleNamespace(
            tls_secret=local_member,
            service_id=TARGET_SERVICE_ID,
            service=service,
            service_ca_certchain=self.target_service_ca,
        )
        account = SimpleNamespace(
            memberships={TARGET_SERVICE_ID: membership},
        )
        config.server = SimpleNamespace(
            account=account,
            network=SimpleNamespace(
                name=NETWORK, paths=self.paths, root_ca=self.root_ca,
            ),
            server_type=ServerType.POD,
        )

    async def _create_service_branch(
        self, service_id: int
    ) -> tuple[ServiceCaSecret, MembersCaSecret, AppsCaSecret]:
        service_ca = ServiceCaSecret(service_id, self.network)
        service_ca_csr = await service_ca.create_csr()
        service_ca.from_signed_cert(self.services_ca.sign_csr(service_ca_csr))

        members_ca = MembersCaSecret(service_id, self.network)
        members_ca_csr = await members_ca.create_csr()
        members_ca.from_signed_cert(service_ca.sign_csr(members_ca_csr))

        apps_ca = AppsCaSecret(service_id, self.network)
        apps_ca_csr = await apps_ca.create_csr()
        apps_ca.from_signed_cert(service_ca.sign_csr(apps_ca_csr))

        return service_ca, members_ca, apps_ca

    async def _create_member_secret(
        self, members_ca: MembersCaSecret, service_id: int,
        skip_ca_policy: bool = False,
    ) -> MemberSecret:
        member_secret = MemberSecret(
            uuid4(), service_id, paths=self.paths, network_name=NETWORK
        )
        member_csr = await member_secret.create_csr()
        if skip_ca_policy:
            member_secret.from_signed_cert(
                members_ca.sign_csr(member_csr, expire=365)
            )
        else:
            member_secret.from_signed_cert(members_ca.sign_csr(member_csr))

        return member_secret

    async def _create_app_secret(
        self, apps_ca: AppsCaSecret, service_id: int,
        skip_ca_policy: bool = False,
    ) -> AppSecret:
        app_secret = AppSecret(uuid4(), service_id, self.network)
        app_csr = await app_secret.create_csr(
            f'app-{app_secret.app_id}.{NETWORK}'
        )
        if skip_ca_policy:
            app_secret.from_signed_cert(
                apps_ca.sign_csr(app_csr, expire=365)
            )
        else:
            app_secret.from_signed_cert(apps_ca.sign_csr(app_csr))

        return app_secret

    async def _create_service_secret(
        self, service_ca: ServiceCaSecret, service_id: int,
        skip_ca_policy: bool = False,
    ) -> ServiceSecret:
        service_secret = ServiceSecret(service_id, self.network)
        service_csr = await service_secret.create_csr()
        if skip_ca_policy:
            service_secret.from_signed_cert(
                service_ca.sign_csr(service_csr, expire=2 * 365)
            )
        else:
            service_secret.from_signed_cert(service_ca.sign_csr(service_csr))

        return service_secret

    async def test_rejects_member_cert_signed_by_rogue_service_ca(self) -> None:
        rogue_member = await self._create_member_secret(
            self.rogue_members_ca, TARGET_SERVICE_ID, skip_ca_policy=True
        )
        client_dn = f'CN={rogue_member.common_name}'
        ca_dn = f'CN={self.rogue_members_ca.common_name}'

        auth = RequestAuth('127.0.0.1', HttpMethod.GET)
        await auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn,
            _escaped_cert(rogue_member), None
        )

        with self.assertRaises(HTTPException) as exc:
            auth.check_member_cert(TARGET_SERVICE_ID, config.server.network)
        self.assertEqual(exc.exception.status_code, 403)

    async def test_accepts_member_cert_signed_by_expected_members_ca(
        self
    ) -> None:
        member = await self._create_member_secret(
            self.target_members_ca, TARGET_SERVICE_ID
        )
        client_dn = f'CN={member.common_name}'
        ca_dn = f'CN={self.target_members_ca.common_name}'

        auth = RequestAuth('127.0.0.1', HttpMethod.GET)
        await auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn,
            _escaped_cert(member), None
        )

        auth.check_member_cert(TARGET_SERVICE_ID, config.server.network)

    async def test_rejects_service_cert_signed_by_rogue_service_ca(
        self
    ) -> None:
        rogue_service = await self._create_service_secret(
            self.rogue_service_ca, TARGET_SERVICE_ID, skip_ca_policy=True
        )
        client_dn = f'CN={rogue_service.common_name}'
        ca_dn = f'CN={self.rogue_service_ca.common_name}'

        auth = RequestAuth('127.0.0.1', HttpMethod.GET)
        await auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn,
            _escaped_cert(rogue_service), None
        )

        with self.assertRaises(HTTPException) as exc:
            auth.check_service_cert(config.server.network)
        self.assertEqual(exc.exception.status_code, 403)

    async def test_rejects_service_cert_signed_by_lookalike_service_ca(
        self
    ) -> None:
        lookalike_service_ca = ServiceCaSecret(TARGET_SERVICE_ID, self.network)
        lookalike_service_ca_csr = await lookalike_service_ca.create_csr()
        lookalike_service_ca.from_signed_cert(
            self.services_ca.sign_csr(
                lookalike_service_ca_csr, expire=15 * 365
            )
        )
        lookalike_service = await self._create_service_secret(
            lookalike_service_ca, TARGET_SERVICE_ID
        )
        client_dn = f'CN={lookalike_service.common_name}'
        ca_dn = f'CN={lookalike_service_ca.common_name}'

        auth = RequestAuth('127.0.0.1', HttpMethod.GET)
        await auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn,
            _escaped_cert(lookalike_service), None
        )

        with self.assertRaises(HTTPException) as exc:
            auth.check_service_cert(config.server.network)
        self.assertEqual(exc.exception.status_code, 403)

    async def test_accepts_service_cert_signed_by_expected_service_ca(
        self
    ) -> None:
        service = await self._create_service_secret(
            self.target_service_ca, TARGET_SERVICE_ID
        )
        client_dn = f'CN={service.common_name}'
        ca_dn = f'CN={self.target_service_ca.common_name}'

        auth = RequestAuth('127.0.0.1', HttpMethod.GET)
        await auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn,
            _escaped_cert(service), None
        )

        auth.check_service_cert(config.server.network)

    async def test_rejects_app_cert_signed_by_rogue_service_ca(self) -> None:
        rogue_app = await self._create_app_secret(
            self.rogue_apps_ca, TARGET_SERVICE_ID, skip_ca_policy=True
        )
        client_dn = f'CN={rogue_app.common_name}'
        ca_dn = f'CN={self.rogue_apps_ca.common_name}'

        auth = RequestAuth('127.0.0.1', HttpMethod.GET)
        await auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn,
            _escaped_cert(rogue_app), None
        )

        with self.assertRaises(HTTPException) as exc:
            auth.check_app_cert(TARGET_SERVICE_ID, config.server.network)
        self.assertEqual(exc.exception.status_code, 403)

    async def test_rejects_app_cert_signed_by_rogue_lookalike_apps_ca(
        self
    ) -> None:
        rogue_apps_ca = AppsCaSecret(TARGET_SERVICE_ID, self.network)
        rogue_apps_ca_csr = await rogue_apps_ca.create_csr()
        rogue_apps_ca.from_signed_cert(
            self.rogue_service_ca.sign_csr(rogue_apps_ca_csr, expire=5 * 365)
        )
        rogue_app = await self._create_app_secret(
            rogue_apps_ca, TARGET_SERVICE_ID
        )
        client_dn = f'CN={rogue_app.common_name}'
        ca_dn = f'CN={rogue_apps_ca.common_name}'

        auth = RequestAuth('127.0.0.1', HttpMethod.GET)
        await auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn,
            _escaped_cert(rogue_app), None
        )

        with self.assertRaises(HTTPException) as exc:
            auth.check_app_cert(TARGET_SERVICE_ID, config.server.network)
        self.assertEqual(exc.exception.status_code, 403)

    async def test_accepts_app_cert_signed_by_expected_apps_ca(self) -> None:
        app = await self._create_app_secret(
            self.target_apps_ca, TARGET_SERVICE_ID
        )
        client_dn = f'CN={app.common_name}'
        ca_dn = f'CN={self.target_apps_ca.common_name}'

        auth = RequestAuth('127.0.0.1', HttpMethod.GET)
        await auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn,
            _escaped_cert(app), None
        )

        auth.check_app_cert(TARGET_SERVICE_ID, config.server.network)

    async def test_accepts_app_cert_with_apps_ca_from_local_cache(self) -> None:
        membership = config.server.account.memberships[TARGET_SERVICE_ID]
        membership.service.apps_ca = None
        await self.target_apps_ca.save(
            storage_driver=self.paths.storage_driver, overwrite=True
        )

        app = await self._create_app_secret(
            self.target_apps_ca, TARGET_SERVICE_ID
        )
        client_dn = f'CN={app.common_name}'
        ca_dn = f'CN={self.target_apps_ca.common_name}'

        auth = RequestAuth('127.0.0.1', HttpMethod.GET)
        await auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn,
            _escaped_cert(app), None
        )

        auth.check_app_cert(TARGET_SERVICE_ID, config.server.network)


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mock_environment_vars(TEST_DIR)

        network_data: dict[str, str] = await setup_network()

        await setup_account(network_data)

    @classmethod
    async def asyncTearDown(cls) -> None:
        await ApiClient.close_all()

    async def test_jwt(self) -> None:
        #
        # Test the python JWT module instead of our code so that we can confirm
        # that any regressions come from our code
        #
        directory: str = '/tmp/byoda-tests/auth/network-byoda.net/account-pod'
        with open(f'{directory}/pod-cert.pem', 'rb') as fd:
            cert_pem: bytes = fd.read()
        directory = '/tmp/byoda-tests/auth/private'
        with open(f'{directory}/network-byoda.net-account-pod.key', 'rb') as fd:
            encrypted_key: bytes = fd.read()
        passphrase = PASSWORD.encode('utf-8')
        cert: x509.Certificate = x509.load_pem_x509_certificate(cert_pem, backend=default_backend)
        public_key: any = cert.public_key()
        private_key: any = serialization.load_pem_private_key(
           encrypted_key, password=passphrase, backend=default_backend()
        )
        data: dict[str, str] = {'data': 'test'}
        encoded: str = py_jwt.encode(data, private_key, algorithm='ES256')
        unverified: any = py_jwt.decode(encoded, options={'verify_signature': False})
        self.assertEqual(data, unverified)
        decoded: any = py_jwt.decode(encoded, public_key, algorithms=['ES256'])
        self.assertEqual(data, decoded)

        #
        # Test JWT encoding/decoding in RequestAuth class for a Member JWT
        #
        secret = Secret(
            'network-byoda.net/account-pod/pod-cert.pem',
            'private/network-byoda.net-account-pod.key',
            config.server.document_store.backend
        )
        await secret.load(password=PASSWORD)

        server: PodServer = config.server
        account: Account = server.account
        member: Member = account.memberships[ADDRESSBOOK_SERVICE_ID]
        jwt: JWT = member.create_jwt()
        request_auth: RequestAuth = RequestAuth(
            '127.0.0.1', HttpMethod.GET
        )
        await request_auth.authenticate(
            TlsStatus.NONE, None, None, None, jwt.encoded
        )
        # We do not test for 'auth.is_authenticated' here as RequestAuth
        # is not responsible for determining that
        self.assertEqual(request_auth.auth_source.value, 'token')
        self.assertTrue(
            member.tls_secret.common_name.startswith(
                str(request_auth.member_id)
            )
        )
        self.assertEqual(request_auth.id_type, IdType.MEMBER)

        jwt = account.create_jwt()

        request_auth: RequestAuth = RequestAuth(
            '127.0.0.1', HttpMethod.GET
        )
        await request_auth.authenticate(
            TlsStatus.NONE, None, None, None, jwt.encoded
        )
        # We do not test for 'auth.is_authenticated' here as RequestAuth
        # is not responsible for determining that
        self.assertEqual(request_auth.auth_source.value, 'token')
        self.assertTrue(
            secret.common_name.startswith(str(request_auth.account_id))
        )
        self.assertEqual(request_auth.id_type, IdType.ACCOUNT)

    async def test_cert(self) -> None:
        # flake8: noqa=E501
        client_dn = 'CN=aaaaaaaa-42ee-4574-a620-5dbccf9372fe.accounts.byoda.net'
        ca_dn = 'CN=accounts-ca.byoda.net'
        request_auth: RequestAuth = RequestAuth(
            '127.0.0.1', HttpMethod.GET
        )
        await request_auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn, None, None
        )
        # We do not test for 'auth.is_authenticated' here as RequestAuth
        # is not responsible for determining that
        self.assertEqual(request_auth.auth_source.value, 'cert')
        id: str = client_dn[3:].split('.')[0]
        self.assertEqual(id, request_auth.account_id)
        self.assertEqual(request_auth.id_type, IdType.ACCOUNT)

        # flake8: noqa=E501
        client_dn = 'CN=aaaaaaaa-42ee-4574-a620-5dbccf9372fe.accounts.byoda.net'
        ca_dn = 'CN=members-ca.byoda.net'
        request_auth: RequestAuth = RequestAuth(
            '127.0.0.1', HttpMethod.GET
        )
        await request_auth.authenticate(
            TlsStatus.SUCCESS, client_dn, ca_dn, None, None
        )


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    os.mkdir(TEST_DIR)

    unittest.main()
