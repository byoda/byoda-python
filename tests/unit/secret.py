#!/usr/bin/env python3

'''
Test cases for secrets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import sys
import os
import shutil
import secrets
import filecmp
import unittest

from uuid import UUID
from copy import copy
from random import randint
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import utils
from cryptography.hazmat.primitives import hashes

from byoda.util.logger import Logger

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.account import Account
from byoda.datamodel.claim import Claim

from byoda.servers.pod_server import PodServer

from byoda.secrets.secret import CertChain
from byoda.secrets.data_secret import DataSecret
from byoda.secrets.app_data_secret import AppDataSecret
from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.datastore.data_store import DataStoreType
from byoda.datastore.cache_store import CacheStoreType

from byoda.datatypes import CloudType
from byoda.datatypes import IdType
from byoda.datatypes import ServerRole

from byoda.datastore.document_store import DocumentStoreType

from byoda import config

from tests.lib.util import get_test_uuid

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID


TEST_DIR = '/tmp/byoda-tests/secrets'
NETWORK = 'test.net'
DEFAULT_SCHEMA = 'tests/collateral/dummy-unsigned-service-schema.json'
SERVICE_ID = 12345678
SCHEMA_VERSION = 1
SCHEMA_DIR = f'/network-{NETWORK}/services/service-{SERVICE_ID}'
SCHEMA_FILE = SCHEMA_DIR + '/service_contract.json'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        shutil.rmtree(TEST_DIR)
        os.mkdir(TEST_DIR)
        os.makedirs(TEST_DIR + SCHEMA_DIR)
        shutil.copy(DEFAULT_SCHEMA, TEST_DIR + SCHEMA_FILE)
        config.test_case = True

    async def asyncTearDown(self) -> None:
        pass

    async def test_ca_certchaisn(self) -> None:
        network: Network = await Network.create(NETWORK, TEST_DIR, 'byoda')

        config.server = PodServer(network)
        config.server.network = network
        config.server.paths = network.paths

        await config.server.set_document_store(
            DocumentStoreType.OBJECT_STORE, cloud_type=CloudType('LOCAL'),
            private_bucket='byoda', restricted_bucket='byoda',
            public_bucket='byoda', root_dir=TEST_DIR
        )
        network.services_ca.validate(network.root_ca, with_openssl=True)
        network.accounts_ca.validate(network.root_ca, with_openssl=True)

        # Need to set role to allow loading of unsigned services
        network.roles = [ServerRole.Pod]

        service = Service(network=network)
        await service.examine_servicecontract(SCHEMA_FILE)
        await service.create_secrets(network.services_ca, local=True)

        service.service_ca.validate(network.root_ca, with_openssl=True)
        service.apps_ca.validate(network.root_ca, with_openssl=True)
        service.tls_secret.validate(network.root_ca, with_openssl=True)
        service.data_secret.validate(network.root_ca, with_openssl=True)

        account_id: UUID = get_test_uuid()
        account = Account(account_id, network)

        await account.paths.create_account_directory()

        config.server.account = account

        config.server.bootstrapping: bool = True

        await account.create_secrets(network.accounts_ca)

        await config.server.set_data_store(
            DataStoreType.SQLITE, account.data_secret
        )
        await config.server.set_cache_store(CacheStoreType.SQLITE)

        account.tls_secret.validate(network.root_ca, with_openssl=True)
        account.data_secret.validate(network.root_ca, with_openssl=True)

    async def test_secrets(self) -> None:
        '''
        Create a network CA hierarchy
        '''

        #
        # Test creation of the CA hierarchy
        #
        network: Network = await Network.create(NETWORK, TEST_DIR, 'byoda')
        config.server = PodServer(network)
        config.server.network = network
        config.server.network.account = 'pod'

        await config.server.set_document_store(
            DocumentStoreType.OBJECT_STORE, cloud_type=CloudType('LOCAL'),
            private_bucket='byoda', restricted_bucket='byoda',
            public_bucket='byoda', root_dir=TEST_DIR
        )

        # Need to set role to allow loading of unsigned services
        network.roles = [ServerRole.Pod]

        shutil.copy(DEFAULT_SCHEMA, TEST_DIR + SCHEMA_FILE)
        service = Service(network=network)
        await service.examine_servicecontract(SCHEMA_FILE)
        await service.create_secrets(network.services_ca, local=True)

        account_id: UUID = get_test_uuid()
        account = Account(account_id, network)
        await account.paths.create_account_directory()
        await account.create_secrets(network.accounts_ca)

        config.server.account = account
        config.server.bootstrapping: bool = True

        config.server.paths = network.paths
        await config.server.set_data_store(
            DataStoreType.SQLITE, account.data_secret
        )
        await config.server.set_cache_store(CacheStoreType.SQLITE)

        network.services_ca.validate(network.root_ca, with_openssl=True)
        network.accounts_ca.validate(network.root_ca, with_openssl=True)

        # Create a dummy entry for the services in the network, otherwise
        # account.join(service) fails
        network.services = {SERVICE_ID: service}

        target_dir: str = f'/network-{NETWORK}/account-pod/service-{SERVICE_ID}'
        os.makedirs(TEST_DIR + target_dir)
        target_schema: str = target_dir + '/service-contract.json'
        shutil.copy(DEFAULT_SCHEMA, TEST_DIR + target_schema)

        # TODO: re-enable this test
        # member = await account.join(
        #    SERVICE_ID, SCHEMA_VERSION, members_ca=service.members_ca,
        #    local_service_contract=SCHEMA_FILE
        # )

        # self.assertIsNotNone(member.member_id)
        # member.tls_secret.validate(network.root_ca, with_openssl=True)
        # member.data_secret.validate(network.root_ca, with_openssl=True)

        # Certchain validation fails as network.services_ca
        # is not in the cert chain of account.data_secret and is
        # not the root CA
        with self.assertRaises(ValueError):
            account.data_secret.validate(network.services_ca)

        #
        # Test data encryption
        #
        target_account_id: UUID = get_test_uuid()
        target_account = Account(target_account_id, network, account='test')
        await target_account.paths.create_account_directory()
        await target_account.create_secrets(network.accounts_ca)

        account.data_secret.create_shared_key(target_account.data_secret)
        target_account.data_secret.load_shared_key(
            account.data_secret.protected_shared_key
        )

        self.assertEqual(
            account.data_secret.shared_key,
            target_account.data_secret.shared_key
        )

        with open('/etc/passwd', 'rb') as file_desc:
            data: bytes = file_desc.read()

        ciphertext: bytes = account.data_secret.encrypt(data)

        passwords: bytes = target_account.data_secret.decrypt(ciphertext)

        self.assertEqual(data, passwords)

        await account.create_secrets(network.accounts_ca, renew=True)

        # Test data encryption of large files
        source_file = TEST_DIR + 'bulk_data'
        with open(source_file, 'wb') as file_desc:
            data = secrets.token_bytes((1 << 21) - randint(1, 1 << 10))
            file_desc.write(data)

        protected_file = source_file + '.protected'
        out_file = source_file + '.out'

        data_secret: DataSecret = account.data_secret
        data_secret.create_shared_key()
        data_secret.encrypt_file(source_file, protected_file)
        data_secret.decrypt_file(protected_file, out_file)
        compare_check: bool = filecmp.cmp(source_file, out_file)
        self.assertTrue(compare_check)

        #
        # Tests for App secret
        #
        app_id: UUID = get_test_uuid()
        fqdn = 'testapp.com'
        app_secret = AppDataSecret(app_id, SERVICE_ID, network)
        csr: x509.CertificateSigningRequest = await app_secret.create_csr(fqdn)
        cert_chain: CertChain = service.apps_ca.sign_csr(csr)

        await cert_chain.save(
            app_secret.cert_file, config.server.storage_driver
        )

        #
        # Tests for App Data secret
        #
        app_data_secret = AppDataSecret(app_id, SERVICE_ID, network)
        csr = await app_data_secret.create_csr(fqdn)
        cert_chain = service.apps_ca.sign_csr(csr)

        await cert_chain.save(
            app_data_secret.cert_file, config.server.storage_driver
        )

        app_data_secret.cert = cert_chain.signed_cert

        #
        # Test claims
        #
        object_fields: list[str] = [
            'asset_id', 'asset_name', 'asset_type', 'asset_url',
            'creator', 'published_timestamp', 'annotations', 'creator',
        ]

        asset_id: UUID = get_test_uuid()
        requester_id: UUID = get_test_uuid()
        claim: Claim = Claim.build(
            ['claim A', 'claim B'], app_id, IdType.APP,
            'public_assets', 'asset_id', asset_id,
            object_fields, requester_id, IdType.MEMBER, 'https://signature',
            'https://renewal', 'https://confirmation'
        )
        asset_data: dict[str, any] = {
            'asset_id': asset_id,
            'asset_name': 'test asset',
            'asset_type': 'video',
            'asset_url': 'https://www.byoda.org',
            'creator': 'test',
            'published_timestamp': datetime.now(timezone.utc).isoformat(),
            'annotations': ['test1', 'test2'],
        }

        signature: str = claim.create_signature(asset_data, app_data_secret)

        verify_claim: Claim = Claim.build(
            ['claim A', 'claim B'], app_id, IdType.APP,
            'public_assets', 'asset_id', asset_id,
            object_fields, requester_id, IdType.MEMBER, 'https://signature',
            'https://renewal', 'https://confirmation'
        )
        verify_claim.claim_id = claim.claim_id
        verify_claim.signature_timestamp = claim.signature_timestamp
        verify_claim.signature_format_version = claim.signature_format_version
        verify_claim.cert_expiration = claim.cert_expiration
        verify_claim.cert_fingerprint = claim.cert_fingerprint

        verify_claim.signature = signature
        verify_claim.verify_signature(asset_data, app_data_secret)
        self.assertTrue(verify_claim.verified)

        data = claim.as_dict()
        new_claim: Claim = Claim.from_dict(data)
        new_claim.verify_signature(asset_data, app_data_secret)
        self.assertTrue(new_claim.verified)

    async def test_message_signature(self) -> None:
        # Test creation of the CA hierarchy
        network: Network = await Network.create(NETWORK, TEST_DIR, 'byoda')

        config.server = PodServer(network)
        config.server.network = network
        await config.server.set_document_store(
            DocumentStoreType.OBJECT_STORE, cloud_type=CloudType('LOCAL'),
            private_bucket='byoda', restricted_bucket='byoda',
            public_bucket='byoda', root_dir=TEST_DIR
        )

        key: rsa.RSAPrivateKey = rsa.generate_private_key(
           public_exponent=65537,
           key_size=4096,
        )

        subject: x509.Name
        issue: x509.Name
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
                x509.NameAttribute(
                    NameOID.STATE_OR_PROVINCE_NAME, u"California"
                ),
                x509.NameAttribute(NameOID.LOCALITY_NAME, u"Los Gatos"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"byoda"),
                x509.NameAttribute(NameOID.COMMON_NAME, u"byoda.org"),
            ]
        )

        cert: x509.Certificate = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + timedelta(days=1)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
            critical=False,
        ).sign(key, hashes.SHA256())

        _RSA_SIGN_MAX_MESSAGE_LENGTH = 1024
        message: bytes = 'ik ben toch niet gek!'.encode('utf-8')
        chosen_hash = hashes.SHA256()
        hasher = hashes.Hash(chosen_hash)
        message = copy(message)
        while message:
            if len(message) > _RSA_SIGN_MAX_MESSAGE_LENGTH:
                hasher.update(message[:_RSA_SIGN_MAX_MESSAGE_LENGTH])
                message = message[_RSA_SIGN_MAX_MESSAGE_LENGTH:]
            else:
                hasher.update(message)
                message = None
        digest: bytes = hasher.finalize()
        signature: bytes = key.sign(
            digest,
            padding.PSS(
                mgf=padding.MGF1(chosen_hash),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            utils.Prehashed(chosen_hash)
            )

        cert.public_key().verify(
            signature,
            digest,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            utils.Prehashed(chosen_hash)
        )

        account = Account(get_test_uuid(), network)
        message = 'ik ben toch niet gek!'

        member_data_secret = MemberDataSecret(
            get_test_uuid(), ADDRESSBOOK_SERVICE_ID, account
        )

        member_data_secret.cert_file = 'azure-pod-member-data-cert.pem'
        member_data_secret.private_key_file = 'azure-pod-member-data.key'
        shutil.copy(
            f'tests/collateral/local/{member_data_secret.cert_file}',
            TEST_DIR
        )
        shutil.copy(
            f'tests/collateral/local/{member_data_secret.private_key_file}',
            TEST_DIR
        )
        with open('tests/collateral/local/azure-pod-private-key-password'
                  ) as file_desc:
            private_key_password = file_desc.read().strip()

        await member_data_secret.load(
            with_private_key=True, password=private_key_password
        )
        signature = member_data_secret.sign_message(message)
        member_data_secret.verify_message_signature(message, signature)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
