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
from byoda.util import Paths

from byoda.datatypes import CsrSource

from byoda.util.secrets import NetworkRootCaSecret
from byoda.util.secrets import NetworkAccountsCaSecret
from byoda.util.secrets import NetworkServicesCaSecret
from byoda.util.secrets import ServiceCaSecret
from byoda.util.secrets import MembersCaSecret
from byoda.util.secrets import ServiceSecret
from byoda.util.secrets import AccountSecret
from byoda.util.secrets import MemberSecret


TEST_DIR = '/tmp/byoda-func-test-secrets'
NETWORK = 'byoda.net'


class TestAccountManager(unittest.TestCase):
    def test_secrets(self):
        account_alias = 'test'
        paths = Paths(
            root_directory=TEST_DIR,
            account_alias=account_alias,
            network_name=NETWORK,
        )
        paths.create_account_directory()
        paths.create_secrets_directory()

        network_root_ca = NetworkRootCaSecret(paths)
        network_root_ca.create(expire=10950)
        network_root_ca.save()

        # Here we make the network_accounts_ca get the signature from the
        # network_root_ca
        network_accounts_ca = NetworkAccountsCaSecret(paths)
        csr = network_accounts_ca.create_csr()
        network_accounts_ca.get_csr_signature(
            csr, network_root_ca, expire=3650
        )
        network_accounts_ca.save()

        # Here we make the network_accounts_ca sign the CSR for the account
        account_id = uuid4()
        account_secret = AccountSecret(paths)
        csr = account_secret.create_csr(account_id)
        commonname = network_accounts_ca.review_csr(csr)
        self.assertIsNotNone(commonname)
        account_secret.add_signed_cert(
            network_accounts_ca.sign_csr(
                csr, expire=3650
            )
        )
        account_secret.save()

        target_account_secret = AccountSecret(paths)
        csr = target_account_secret.create_csr(account_id)
        commonname = network_accounts_ca.review_csr(csr)
        self.assertIsNotNone(commonname)
        target_account_secret.add_signed_cert(
            network_accounts_ca.sign_csr(
                csr, expire=3650
            )
        )

        account_secret.create_shared_key(target_account_secret)
        target_account_secret.load_shared_key(
            account_secret.protected_shared_key
        )

        self.assertEqual(
            account_secret.shared_key, target_account_secret.shared_key
        )

        with open('/etc/passwd', 'rb') as file_desc:
            data = file_desc.read()

        ciphertext = account_secret.encrypt(data)

        passwords = target_account_secret.decrypt(ciphertext)

        self.assertEqual(data, passwords)

        # create some more secrets to have full coverage
        network_service_ca = NetworkServicesCaSecret(paths)
        csr = network_service_ca.create_csr()
        network_service_ca.get_csr_signature(csr, network_root_ca, expire=3650)
        network_service_ca.save()

        service_id = pow(2, 64) - 2
        service_alias = 'mytestservice'
        paths.create_service_directory(service_alias)

        service_ca = ServiceCaSecret(service_alias, paths)
        csr = service_ca.create_csr(service_id)
        commonname = network_service_ca.review_csr(csr)
        self.assertIsNotNone(commonname)
        service_ca.add_signed_cert(
            network_service_ca.sign_csr(csr, expire=3650)
        )
        service_ca.save()

        service_secret = ServiceSecret(service_alias, paths)
        csr = service_secret.create_csr(service_id)
        commonname = service_ca.review_csr(csr, source=CsrSource.LOCAL)
        self.assertIsNotNone(commonname)
        service_secret.add_signed_cert(
            service_ca.sign_csr(csr, expire=3650)
        )
        service_secret.save()

        service_members_ca = MembersCaSecret(service_alias, paths)
        csr = service_members_ca.create_csr(service_id)
        commonname = service_ca.review_csr(csr, source=CsrSource.LOCAL)
        self.assertIsNotNone(commonname)
        service_members_ca.add_signed_cert(
            service_ca.sign_csr(csr, expire=3650)
        )
        service_members_ca.save()

        member_id = uuid4()
        member_secret = MemberSecret(service_alias, paths)
        csr = member_secret.create_csr(NETWORK, service_id, member_id)
        commonname = service_members_ca.review_csr(csr)
        self.assertIsNotNone(commonname)
        member_secret.add_signed_cert(
            service_members_ca.sign_csr(csr, expire=3650)
        )
        paths.create_member_directory(service_alias)
        member_secret.save()

        load_secrets(paths)


def load_secrets(paths):
    network_root_ca = NetworkRootCaSecret(paths)
    network_root_ca.load()

    network_accounts_ca = NetworkAccountsCaSecret(paths)
    network_accounts_ca.load()

    account_secret = AccountSecret(paths)
    account_secret.load()

    account_secret.validate(network_root_ca)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    os.mkdir(TEST_DIR)

    unittest.main()
