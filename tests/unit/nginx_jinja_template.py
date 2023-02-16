#!/usr/bin/env python3

'''
Test to troubleshoot issues with Jinja2 schemas

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from byoda.util.nginxconfig import NginxConfig

from tests.lib.util import get_test_uuid

TEST_DIR = '/tmp/byoda-tests/nginx-jinja'

os.makedirs(TEST_DIR, exist_ok=True)

nginx = NginxConfig(
    TEST_DIR, 'testfile', get_test_uuid(), 'accounts',
    '/test/cert.pem', '/test/key.pem',  'some-alias?', 'test-network',
    'public_clout_endpoint', 'private_cloud_endpoint', 444, service_id=999
)
data = nginx.create()

nginx = NginxConfig(
    TEST_DIR, 'testfile', get_test_uuid(), 'members-999',
    '/test/cert.pem', '/test/key.pem',  'some-alias?', 'test-network',
    'public_clout_endpoint', 'private_cloud_endpoint', 444, service_id=999
)

data = nginx.create()

nginx = NginxConfig(
    TEST_DIR, 'testfile', get_test_uuid(), 'accounts',
    '/test/cert.pem', '/test/key.pem',  'some-alias?', 'test-network',
    'public_clout_endpoint', 'private_cloud_endpoint', 444, service_id=999,
    custom_domain='byoda.me'
)

data = nginx.create()

nginx = NginxConfig(
    TEST_DIR, 'testfile', get_test_uuid(), 'members-999',
    '/test/cert.pem', '/test/key.pem',  'some-alias?', 'test-network',
    'public_clout_endpoint', 'private_cloud_endpoint', 444, service_id=999,
    custom_domain='byoda.me'
)

data = nginx.create()
