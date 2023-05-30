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
    'public_cloud_endpoint', 'restricted_cloud_endpoint',
    'private_cloud_endpoint', cloud='Azure', service_id=999, port=444,
    public_bucket='public_bucket', restricted_bucket='restricted_bucket'
)
data = nginx.create()

nginx = NginxConfig(
    TEST_DIR, 'testfile', get_test_uuid(), 'members-999',
    '/test/cert.pem', '/test/key.pem',  'some-alias?', 'test-network',
    'public_clout_endpoint', 'restricted_cloud_endpoint',
    'private_cloud_endpoint', cloud='Azure', service_id=999, port=444,
    public_bucket='public_bucket', restricted_bucket='restricted_bucket'
)

data = nginx.create()

nginx = NginxConfig(
    TEST_DIR, 'testfile', get_test_uuid(), 'accounts',
    '/test/cert.pem', '/test/key.pem',  'some-alias?', 'test-network',
    'public_clout_endpoint', 'restricted_cloud_endpoint',
    'private_cloud_endpoint', cloud='Azure', service_id=999, port=444,
    custom_domain='byoda.me', public_bucket='public_bucket',
    restricted_bucket='restricted_bucket'
)

data = nginx.create()

nginx = NginxConfig(
    TEST_DIR, 'testfile', get_test_uuid(), 'members-999',
    '/test/cert.pem', '/test/key.pem',  'some-alias?', 'test-network',
    'public_clout_endpoint', 'restricted_cloud_endpoint',
    'private_cloud_endpoint', cloud='Azure', service_id=999, port=444,
    custom_domain='byoda.me', public_bucket='public_bucket',
    restricted_bucket='restricted_bucket'
)

data = nginx.create()

nginx = NginxConfig(
    TEST_DIR, 'testfile', get_test_uuid(), 'members-999',
    '/test/cert.pem', '/test/key.pem',  'some-alias?', 'test-network',
    'public_clout_endpoint', 'restricted_cloud_endpoint',
    'private_cloud_endpoint', cloud='LOCAL', service_id=999, port=444,
    custom_domain='byoda.me', public_bucket='public_bucket',
    restricted_bucket='restricted_bucket'
)

data = nginx.create()
