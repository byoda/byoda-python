#!/usr/bin/env python3

'''
Test cases for authentication of REST / Data API calls

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest

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

from byoda.requestauth.requestauth import RequestAuth

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.member import Secret

from byoda.servers.pod_server import PodServer

from byoda.datatypes import IdType
from byoda.datatypes import TlsStatus

from byoda.requestauth.jwt import JWT

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpMethod

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID


CONFIG_FILE = 'tests/collateral/config.yml'

TEST_DIR = '/tmp/byoda-tests/auth'


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
        passphrase = b'byoda'
        cert: x509.Certificate = x509.load_pem_x509_certificate(cert_pem, backend=default_backend)
        public_key: any = cert.public_key()
        private_key: any = serialization.load_pem_private_key(
           encrypted_key, password=passphrase, backend=default_backend()
        )
        data: dict[str, str] = {'data': 'test'}
        encoded: str = py_jwt.encode(data, private_key, algorithm='RS256')
        unverified: any = py_jwt.decode(encoded, options={'verify_signature': False})
        self.assertEqual(data, unverified)
        decoded: any = py_jwt.decode(encoded, public_key, algorithms=['RS256'])
        self.assertEqual(data, decoded)

        #
        # Test JWT encoding/decoding in RequestAuth class for a Member JWT
        #
        secret = Secret(
            'network-byoda.net/account-pod/pod-cert.pem',
            'private/network-byoda.net-account-pod.key',
            config.server.document_store.backend
        )
        await secret.load()

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

    async def test_cert(self):
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
        id = client_dn[3:].split('.')[0]
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
