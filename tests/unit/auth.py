#!/usr/bin/env python3

'''
Test cases for authentication of REST / GraphQL API calls

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest
from uuid import uuid4, UUID

import jwt as py_jwt

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography import x509

from byoda.requestauth import RequestAuth
from byoda.requestauth.jwt import JWT

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.member import Secret

from byoda.servers.pod_server import PodServer

from byoda.datastore.document_store import DocumentStoreType
from byoda.datatypes import CloudType, IdType
from byoda.datatypes import TlsStatus
from byoda.datatypes import HttpRequestMethod


from podserver.util import get_environment_vars

from byoda.util.logger import Logger

from byoda import config

from tests.lib.util import get_test_uuid
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
CONFIG_FILE = 'tests/collateral/config.yml'

TEST_DIR = '/tmp/byoda-tests/auth'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        os.environ['ROOT_DIR'] = TEST_DIR
        os.environ['BUCKET_PREFIX'] = 'byoda'
        os.environ['CLOUD'] = 'LOCAL'
        os.environ['NETWORK'] = 'byoda.net'
        os.environ['ACCOUNT_ID'] = str(get_test_uuid())
        os.environ['ACCOUNT_SECRET'] = 'test'
        os.environ['LOGLEVEL'] = 'DEBUG'
        os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
        os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

        # Remaining environment variables used:
        network_data = get_environment_vars()

        network = Network(network_data, network_data)
        await network.load_network_secrets()

        config.server = PodServer(network)
        server = config.server

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType(network_data['cloud']),
            bucket_prefix=network_data['bucket_prefix'],
            root_dir=network_data['root_dir']
        )

        server.paths = network.paths

        pod_account = Account(network_data['account_id'], network)
        await pod_account.paths.create_account_directory()
        await pod_account.load_memberships()

        server.account = pod_account

        await pod_account.create_account_secret()
        await pod_account.create_data_secret()
        await pod_account.register()

        await server.get_registered_services()

        member_id = get_test_uuid()
        await pod_account.join(ADDRESSBOOK_SERVICE_ID, 1, member_id=member_id)

    async def test_jwt(self):
        #
        # Test the python JWT module instead of our code so that we can confirm
        # that any regressions come from our code
        #
        with open('/tmp/byoda-tests/auth/network-byoda.net/account-pod/pod-cert.pem', 'rb') as fd:
            cert_pem = fd.read()
        with open('/tmp/byoda-tests/auth/private/network-byoda.net-account-pod.key', 'rb') as fd:
            encrypted_key = fd.read()
        passphrase = b'byoda'
        cert = x509.load_pem_x509_certificate(cert_pem, backend=default_backend)
        public_key = cert.public_key()
        private_key = serialization.load_pem_private_key(
           encrypted_key, password=passphrase, backend=default_backend()
        )
        data = {'data': 'test'}
        encoded = py_jwt.encode(data, private_key, algorithm='RS256')
        unverified = py_jwt.decode(encoded, options={'verify_signature': False})
        self.assertEqual(data, unverified)
        decoded = py_jwt.decode(encoded, public_key, algorithms=['RS256'])
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
        jwt = member.create_jwt()
        request_auth: RequestAuth = RequestAuth(
            '127.0.0.1', HttpRequestMethod.GET
        )
        await request_auth.authenticate(TlsStatus.NONE, None, None, jwt.encoded)
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
            '127.0.0.1', HttpRequestMethod.GET
        )
        await request_auth.authenticate(TlsStatus.NONE, None, None, jwt.encoded)
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
            '127.0.0.1', HttpRequestMethod.GET
        )
        await request_auth.authenticate(TlsStatus.SUCCESS, client_dn, ca_dn, None)
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
            '127.0.0.1', HttpRequestMethod.GET
        )
        await request_auth.authenticate(TlsStatus.SUCCESS, client_dn, ca_dn, None)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    os.mkdir(TEST_DIR)

    unittest.main()
