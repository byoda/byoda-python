#!/usr/bin/env python3

'''
Test the Directory APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license
'''

import sys

from uuid import UUID, uuid4
import unittest
import requests
import yaml

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from byoda.util.logger import Logger
from byoda.config import DEFAULT_NETWORK
from byoda.util.secrets import AccountSecret

from byoda.datamodel import Network

BASE_URL = 'http://localhost:8000/api'

# Settings must match config.yml used by directory server
NETWORK = DEFAULT_NETWORK


class TestDirectoryApis(unittest.TestCase):
    def test_network_account_get(self):
        API = BASE_URL + '/v1/network/account'

        with open('config.yml') as file_desc:
            app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)
            network_name = app_config['application']['network']

        uuid = uuid4()
        # GET, no auth
        response = requests.get(API)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        print(data)
        self.assertEqual(data['accounts'], 1)
        self.assertEqual(data['remote_addr'], '127.0.0.1')
        UUID(data['uuid'])

        # GET, with auth
        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={uuid}.accounts.{network_name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network_name}'
        }
        response = requests.get(API, headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['accounts'], 1)
        self.assertEqual(data['remote_addr'], '127.0.0.1')
        UUID(data['uuid'])

        # GET, with auth
        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={uuid}.accounts.{network_name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network_name}'
        }
        response = requests.get(API, headers=headers)
        data = response.json()
        self.assertEqual(data['accounts'], 1)
        self.assertEqual(data['remote_addr'], '127.0.0.1')
        UUID(data['uuid'])

    def test_network_account_post(self):
        API = BASE_URL + '/v1/network/account'

        with open('config.yml') as file_desc:
            app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

        network = Network(app_config['dirserver'], app_config['application'])

        uuid = uuid4()
        secret = AccountSecret(
            account='dir_api_test', account_id=uuid, network=network
        )
        csr = secret.create_csr()
        csr = csr.public_bytes(serialization.Encoding.PEM)
        fqdn = AccountSecret.create_fqdn(uuid, network.network)
        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={fqdn}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.network}'
        }
        response = requests.post(
            API, json={'csr': str(csr, 'utf-8')}, headers=headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        issuing_ca_cert = x509.load_pem_x509_certificate(   # noqa
            data['cert_chain'].encode()
        )
        account_cert = x509.load_pem_x509_certificate(      # noqa
            data['signed_cert'].encode()
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
