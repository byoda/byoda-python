#!/usr/bin/env python3

'''
Test the Directory APIs

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license
'''

import sys
import os
import unittest
import requests
import shutil
import yaml
import json
from uuid import uuid4
from copy import copy

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from multiprocessing import Process
import uvicorn

from byoda.datamodel import Network
from byoda.datamodel import DirectoryServer
from byoda.datamodel import Service

from byoda.util.secrets import Secret
from byoda.util.secrets import AccountSecret
from byoda.util.secrets import ServiceCaSecret
from byoda.util.secrets import ServiceSecret

from byoda.util.logger import Logger
from byoda.util import Paths

from byoda import config

from dirserver.api import setup_api


# Settings must match config.yml used by directory server
NETWORK = 'test.net'
DEFAULT_SCHEMA = 'tests/collateral/dummy-unsigned-service-schema.json'
SERVICE_ID = 12345678

CONFIG_FILE = 'tests/collateral/config.yml'
TEST_DIR = '/tmp/byoda-tests/dir_apis'
TEST_PORT = 9000
BASE_URL = f'http://localhost:{TEST_PORT}/api'

_LOGGER = None


class TestDirectoryApis(unittest.TestCase):
    PROCESS = None
    APP_CONFIG = None

    @classmethod
    def setUpClass(cls):
        _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        with open(CONFIG_FILE) as file_desc:
            cls.APP_CONFIG = yaml.load(file_desc, Loader=yaml.SafeLoader)

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        app = setup_api(
            'Byoda test dirserver', 'server for testing directory APIs',
            'v0.0.1', None
        )
        cls.PROCESS = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={
                'host': '127.0.0.1',
                'port': TEST_PORT,
                'log_level': 'debug'
            },
            daemon=True
        )
        cls.PROCESS.start()
        network = Network.create(
            cls.APP_CONFIG['application']['network'],
            cls.APP_CONFIG['application']['root_dir'],
            cls.APP_CONFIG['dirserver']['private_key_password']
        )

        config.server = DirectoryServer()
        config.server.network = network
        config.network = network

        service = Service(network, DEFAULT_SCHEMA)
        service.create_secrets(network.services_ca)

    @classmethod
    def tearDownClass(cls):
        cls.PROCESS.terminate()

    def test_network_account_put(self):
        API = BASE_URL + '/v1/network/account'

        uuid = uuid4()

        network_name = TestDirectoryApis.APP_CONFIG['application']['network']

        # PUT, with auth
        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={uuid}.accounts.{network_name}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network_name}'
        }
        response = requests.put(API, headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ipv4_address'], '127.0.0.1')
        self.assertEqual(data['ipv6_address'], None)

    def test_network_account_post(self):
        API = BASE_URL + '/v1/network/account'

        network = Network(
            TestDirectoryApis.APP_CONFIG['dirserver'],
            TestDirectoryApis.APP_CONFIG['application']
        )

        uuid = uuid4()
        secret = AccountSecret(
            account='dir_api_test', account_id=uuid, network=network
        )
        csr = secret.create_csr()
        csr = csr.public_bytes(serialization.Encoding.PEM)
        fqdn = AccountSecret.create_commonname(uuid, network.name)
        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={fqdn}',
            'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network.name}'
        }
        response = requests.post(
            API, json={'csr': str(csr, 'utf-8')}, headers=headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        issuing_ca_cert = x509.load_pem_x509_certificate(       # noqa:F841
            data['cert_chain'].encode()
        )
        account_cert = x509.load_pem_x509_certificate(          # noqa:F841
            data['signed_cert'].encode()
        )
        network_root_ca_cert = x509.load_pem_x509_certificate(  # noqa:F841
            data['network_root_ca_cert'].encode()
        )
        network_data_cert = x509.load_pem_x509_certificate(     # noqa:F841
            data['network_root_ca_cert'].encode()
        )

    def test_network_service_get(self):
        API = BASE_URL + '/v1/network/service'

        response = requests.get(API)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        summary = data['service_summaries'][0]
        self.assertEqual(summary['service_id'], 0)
        self.assertEqual(summary['version'], 0)
        self.assertEqual(summary['name'], 'private')

    def test_network_service_creation(self):
        API = BASE_URL + '/v1/network/service'

        with open('config.yml') as file_desc:
            app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

        network = Network(app_config['dirserver'], app_config['application'])

        config.server = DirectoryServer()
        config.server.network = network

        service_id = SERVICE_ID
        secret = ServiceCaSecret(
            service='dir_api_test', service_id=service_id, network=network
        )
        csr = secret.create_csr()
        csr = csr.public_bytes(serialization.Encoding.PEM)

        response = requests.post(
            API, json={'csr': str(csr, 'utf-8')}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        issuing_ca_cert = x509.load_pem_x509_certificate(       # noqa:F841
            data['cert_chain'].encode()
        )
        serviceca_cert = x509.load_pem_x509_certificate(        # noqa:F841
            data['signed_cert'].encode()
        )
        # TODO: populate a secret from a CertChain
        secret.cert = serviceca_cert

        network_root_ca_cert = x509.load_pem_x509_certificate(  # noqa:F841
            data['network_root_ca_cert'].encode()
        )
        network_data_cert = x509.load_pem_x509_certificate(     # noqa:F841
            data['network_root_ca_cert'].encode()
        )

        service_secret = ServiceSecret('dir_api_test', service_id, network)
        service_csr = service_secret.create_csr()
        certchain = secret.sign_csr(service_csr)
        service_cn = Secret.extract_commonname(certchain.signed_cert)

        serviceca_cn = Secret.extract_commonname(serviceca_cert)

        # Update registration with data cert
        paths = copy(network.paths)
        paths.service_id = service_id
        filepath = paths.get(Paths.SERVICE_DATA_CERT_FILE)
        with open(filepath) as file_desc:
            certchain_pem = file_desc.readlines()

        response = requests.put(API, json={'certchain': certchain_pem})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ipv4_address'], '127.0.0.1')

        # Send the service schema
        with open('tests/collateral/dummy-service-schema.json') as file_desc:
            schema = json.load(file_desc)

        schema['service_id'] = service_id

        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={service_cn}',
            'X-Client-SSL-Issuing-CA': f'CN={serviceca_cn}'
        }

        response = requests.patch(API, headers=headers, json=schema)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        print(data)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
