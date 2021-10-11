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
import time
from uuid import uuid4
from copy import copy

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from multiprocessing import Process
import uvicorn

from byoda.datamodel import Network
from byoda.datamodel import DirectoryServer
from byoda.datamodel import Service
from byoda.datamodel import Schema
from byoda.util.message_signature import SignatureType

from byoda.util.secrets import Secret, data_secret
from byoda.util.secrets import AccountSecret
from byoda.util.secrets import ServiceCaSecret
from byoda.util.secrets import ServiceSecret
from byoda.util.secrets import ServiceDataSecret

from byoda.util.logger import Logger
from byoda.util import Paths

from byoda import config

from byoda.datastore import DnsDb

from dirserver.api import setup_api


# Settings must match config.yml used by directory server
NETWORK = 'test.net'
DEFAULT_SCHEMA = 'tests/collateral/dummy-unsigned-service-schema.json'
SERVICE_ID = 12345678

CONFIG_FILE = 'tests/collateral/config.yml'
TEST_DIR = '/tmp/byoda-tests/dir_apis'
SERVICE_DIR = TEST_DIR + '/service'
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
        os.makedirs(
            f'{SERVICE_DIR}/network-{cls.APP_CONFIG["application"]["network"]}'
            f'/services/service-{SERVICE_ID}'
        )

        network = Network.create(
            cls.APP_CONFIG['application']['network'],
            cls.APP_CONFIG['application']['root_dir'],
            cls.APP_CONFIG['dirserver']['private_key_password']
        )
        network.dnsdb = DnsDb.setup(
           cls.APP_CONFIG['dirserver']['dnsdb'], network.name
        )
        config.server = DirectoryServer()
        config.server.network = network
        config.network = network

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
        time.sleep(3)

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

    def test_network_service_creation(self):
        API = BASE_URL + '/v1/network/service'

        # We can not use deepcopy here so do two copies
        network = copy(config.server.network)
        network.paths = copy(config.server.network.paths)
        network.paths._root_directory = SERVICE_DIR

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

        # Check that the service CA public cert was written to the network
        # directory of the dirserver
        testsecret = ServiceCaSecret(
            service='dir_api_test', service_id=service_id,
            network=config.server.network
        )
        testsecret.load(with_private_key=False)

        service_secret = ServiceSecret('dir_api_test', service_id, network)
        service_csr = service_secret.create_csr()
        certchain = secret.sign_csr(service_csr)
        service_cn = Secret.extract_commonname(certchain.signed_cert)

        serviceca_cn = Secret.extract_commonname(serviceca_cert)

        # Create and register the the public cert of the data secret,
        # which the directory server needs to validate the service signature
        # of the schema for the service
        service_data_secret = ServiceDataSecret(
            'dir_api_test', service_id, network
        )
        service_data_csr = service_data_secret.create_csr()
        data_certchain = secret.sign_csr(service_data_csr)
        service_data_secret.from_signed_cert(data_certchain)

        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={service_cn}',
            'X-Client-SSL-Issuing-CA': f'CN={serviceca_cn}'
        }

        data_certchain = service_data_secret.certchain_as_pem()
        response = requests.put(
            API + '/' + str(service_id), headers=headers,
            json={'certchain': data_certchain}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ipv4_address'], '127.0.0.1')

        # Send the service schema
        with open(DEFAULT_SCHEMA) as file_desc:
            schema_data = json.load(file_desc)

        schema_data['service_id'] = service_id
        schema_data['version'] = 1

        schema = Schema(schema_data)
        schema.create_signature(service_data_secret, SignatureType.SERVICE)

        headers = {
            'X-Client-SSL-Verify': 'SUCCESS',
            'X-Client-SSL-Subject': f'CN={service_cn}',
            'X-Client-SSL-Issuing-CA': f'CN={serviceca_cn}'
        }

        response = requests.patch(
            API, headers=headers, json=schema.json_schema
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ACCEPTED')
        self.assertEqual(len(data['errors']), 0)

        # Get the fully-signed data contract for the service
        API = BASE_URL + f'/v1/network/service/{service_id}'

        response = requests.get(API)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 9)
        self.assertEqual(data['service_id'], SERVICE_ID)
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['name'], 'dummyservice')
        self.assertEqual(len(data['signatures']), 2)

        # Get the list of service summaries
        API = BASE_URL + '/v1/network/services'
        response = requests.get(API)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        service_summary = data['service_summaries'][0]
        self.assertEqual(service_summary['service_id'], SERVICE_ID)
        self.assertEqual(service_summary['version'], 1)
        self.assertEqual(service_summary['name'], 'dummyservice')


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
