#!/usr/bin/env python3

'''
Verify that the POD sends out CORS headers when presented
with an allowed origin header

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import unittest

import requests
from requests.structures import CaseInsensitiveDict

from byoda.util.logger import Logger


from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import AZURE_POD_ACCOUNT_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID

TEST_DIR = '/tmp/byoda-tests/proxy_test'


class TestCors(unittest.TestCase):
    def test_cors_headers(self):
        direct_account_fqdn = f'{AZURE_POD_ACCOUNT_ID}.accounts.byoda.net'
        do_request(self, direct_account_fqdn)

        direct_member_fqdn = \
            f'{AZURE_POD_MEMBER_ID}.members-{ADDRESSBOOK_SERVICE_ID}.byoda.net'
        do_request(self, direct_member_fqdn)

        proxy_fqdn = 'proxy.byoda.net'

        proxy_account_api_prefix = f'/{AZURE_POD_ACCOUNT_ID}'
        do_request(
            self, proxy_fqdn,
            api_prefix=proxy_account_api_prefix
        )

        proxy_member_api_prefix = \
            f'/{ADDRESSBOOK_SERVICE_ID}/{AZURE_POD_MEMBER_ID}'
        do_request(
            self, proxy_fqdn,
            api_prefix=proxy_member_api_prefix
        )


def do_request(testcase, fqdn: str, api_prefix: str = '/'):
    if api_prefix and api_prefix[-1] != '/':
        api_prefix = api_prefix + '/'

    location = f'https://{fqdn}'
    url = f'{location}{api_prefix}api/v1/status'

    request_headers = CaseInsensitiveDict()
    request_headers['Access-Control-Request-Method'] = 'POST'
    request_headers['Access-Control-Request-Headers'] = 'content-type'
    request_headers['Origin'] = location

    resp = requests.options(url, verify=False, headers=request_headers)
    testcase.assertEqual(resp.status_code, 200)

    testcase.assertEqual(
        resp.headers['access-control-allow-methods'],
        'DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT'
    )
    testcase.assertEqual(resp.headers['access-control-max-age'], '600')

    testcase.assertEqual(
        resp.headers['access-control-allow-credentials'], 'true'
    )
    testcase.assertEqual(resp.headers['access-control-allow-origin'], location)
    testcase.assertEqual(
        resp.headers['access-control-allow-headers'], 'content-type'
    )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
