#!/usr/bin/env python3

'''
Test the Secret class
'''

import sys
import os
import shutil
from uuid import uuid4
import unittest

from byoda.util import Logger
from byoda.config import DEFAULT_NETWORK

from byoda.datamodel import Network, Service, Account

TEST_DIR = '/tmp/byoda-func-test-secrets'
NETWORK = DEFAULT_NETWORK
DEFAULT_SCHEMA = 'services/default.json'


class TestAccountManager(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TEST_DIR)
        os.mkdir(TEST_DIR)

    def test_secrets(self):
        '''
        Create a network CA hierarchy
        '''

        #
        # Test creation of the CA hierarchy
        network = Network.create('test.net', TEST_DIR, 'byoda')
        service = Service(network, DEFAULT_SCHEMA)
        service.create_secrets(network.services_ca)

        account_id = uuid4()
        account = Account(account_id, network)
        account.create_secrets(network.accounts_ca)

        member = account.join(
            service=service, members_ca=service.members_ca

        )
        self.assertIsNotNone(member.member_id)
        account.data_secret.validate(network.root_ca)

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
        target_account.create_secrets(network.accounts_ca)

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


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    os.mkdir(TEST_DIR)

    unittest.main()
