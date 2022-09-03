#!/usr/bin/env python3

'''
Test cases for secrets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import sys
import os
import shutil
import unittest
from copy import copy
from uuid import uuid4
from datetime import datetime, timedelta

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

from byoda.servers.pod_server import PodServer
from byoda.servers.directory_server import DirectoryServer

from byoda.datastore.document_store import DocumentStoreType

from byoda.datatypes import CloudType, ServerRole

from byoda import config

TEST_DIR = '/tmp/byoda-tests/secrets'
NETWORK = 'test.net'
DEFAULT_SCHEMA = 'tests/collateral/dummy-unsigned-service-schema.json'
SERVICE_ID = 12345678
SCHEMA_VERSION = 1


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        shutil.rmtree(TEST_DIR)
        os.mkdir(TEST_DIR)

    async def test_secrets(self):
        '''
        Create a network CA hierarchy
        '''

        #
        # Test creation of the CA hierarchy
        network = await Network.create(NETWORK, TEST_DIR, 'byoda')

        config.server = DirectoryServer(network)
        config.server.network = network
        await config.server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType('LOCAL'),
            bucket_prefix='byoda',
            root_dir=TEST_DIR
        )

        network.services_ca.validate(network.root_ca, with_openssl=True)
        network.accounts_ca.validate(network.root_ca, with_openssl=True)

        # Need to set role to allow loading of unsigned services
        network.roles = [ServerRole.Pod]

        target_dir = \
            f'/network-{NETWORK}/services/service-{SERVICE_ID}'
        os.makedirs(TEST_DIR + target_dir)
        target_schema = target_dir + '/service-contract.json'
        shutil.copy(DEFAULT_SCHEMA, TEST_DIR + target_schema)
        service = Service(network=network)
        await service.examine_servicecontract(target_schema)
        await service.create_secrets(network.services_ca, local=True)

        service.service_ca.validate(network.root_ca, with_openssl=True)
        service.apps_ca.validate(network.root_ca, with_openssl=True)
        service.tls_secret.validate(network.root_ca, with_openssl=True)
        service.data_secret.validate(network.root_ca, with_openssl=True)

        account_id = uuid4()
        account = Account(account_id, network)
        await account.paths.create_account_directory()
        await account.load_memberships()
        await account.create_secrets(network.accounts_ca)

        account.tls_secret.validate(network.root_ca, with_openssl=True)
        account.data_secret.validate(network.root_ca, with_openssl=True)

        # Create a dummy entry for the services in the network, otherwise
        # account.join(service) fails
        network.services = {SERVICE_ID: service}

        target_dir = f'/network-{NETWORK}/account-pod/service-{SERVICE_ID}'
        os.makedirs(TEST_DIR + target_dir)
        target_schema = target_dir + '/service-contract.json'
        shutil.copy(DEFAULT_SCHEMA, TEST_DIR + target_schema)

        # TODO: re-enable this test
        # member = account.join(
        #     SERVICE_ID, SCHEMA_VERSION, members_ca=service.members_ca
        # )

        # self.assertIsNotNone(member.member_id)
        # member.tls_secret.validate(network.root_ca, with_openssl=True)
        # member.data_secret.validate(network.root_ca, with_openssl=True)

        # Certchain validation fails as network.services_ca
        # is in the cert chain of account.data_secret and is
        # not the root CA
        with self.assertRaises(ValueError):
            account.data_secret.validate(network.services_ca)

        #
        # Test data encryption
        #
        target_account_id = uuid4()
        target_account = Account(target_account_id, network, account='test')
        await target_account.paths.create_account_directory()
        await target_account.load_memberships()
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
            data = file_desc.read()

        ciphertext = account.data_secret.encrypt(data)

        passwords = target_account.data_secret.decrypt(ciphertext)

        self.assertEqual(data, passwords)

    async def test_message_signature(self):
        # Test creation of the CA hierarchy
        network = await Network.create(NETWORK, TEST_DIR, 'byoda')

        config.server = PodServer(network)
        config.server.network = network
        await config.server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType('LOCAL'),
            bucket_prefix='byoda',
            root_dir=TEST_DIR
        )

        key = rsa.generate_private_key(
           public_exponent=65537,
           key_size=4096,
        )

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

        cert = x509.CertificateBuilder().subject_name(
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
        message = 'ik ben toch niet gek!'.encode('utf-8')
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
        digest = hasher.finalize()
        signature = key.sign(
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


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    os.mkdir(TEST_DIR)

    unittest.main()
