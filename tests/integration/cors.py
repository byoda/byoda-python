#!/usr/bin/env python3

'''
Verify that the POD sends out CORS headers when presented
with an allowed origin header

TODO: fix test case so it doesn't use the proxy when connecting to a pod
with a custom domain

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import unittest

import httpx
from requests.structures import CaseInsensitiveDict

from byoda.util.logger import Logger


from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import TEST_IDS

TEST_DIR = '/tmp/byoda-tests/proxy_test'


class TestCors(unittest.TestCase):
    def test_cors_headers(self):
        for cloud, ids in TEST_IDS.items():
            _LOGGER.debug(f'Testing cloud: {cloud}')

            if cloud != 'home':
                direct_account_fqdn: str = \
                    f'{ids["account_id"]}.accounts.byoda.net'
                do_request(self, cloud, direct_account_fqdn)

                direct_member_fqdn: str = (
                    f'{ids["member_id"]}.members-{ADDRESSBOOK_SERVICE_ID}'
                    '.byoda.net'
                )
                do_request(self, cloud, direct_member_fqdn)

            proxy_fqdn = 'proxy.byoda.net'

            proxy_account_api_prefix = f'/{ids["account_id"]}'
            do_request(
                self, cloud, proxy_fqdn,
                api_prefix=proxy_account_api_prefix
            )

            proxy_member_api_prefix = \
                f'/{ADDRESSBOOK_SERVICE_ID}/{ids["member_id"]}'
            do_request(
                self, cloud, proxy_fqdn,
                api_prefix=proxy_member_api_prefix
            )


def do_request(testcase, cloud: str, fqdn: str, api_prefix: str = '/'):
    if api_prefix and api_prefix[-1] != '/':
        api_prefix = api_prefix + '/'

    locations: list[str] = [
        f'https://{fqdn}',
        'https://www.byoda.net',
        'https://addressbook.byoda.org',
        'https://byoda.tube',
        'https://www.byoda.tube',
        'http://localhost:3000'
    ]

    location: str
    for location in locations:
        do_location(testcase, cloud, fqdn, location, api_prefix)


def do_location(testcase, cloud: str, fqdn: str, location: str,
                api_prefix: str) -> None:
    url: str = f'https://{fqdn}{api_prefix}api/v1/status'

    request_headers = CaseInsensitiveDict()
    request_headers['Access-Control-Request-Method'] = 'POST'
    request_headers['Access-Control-Request-Headers'] = 'content-type'
    request_headers['Origin'] = location

    _LOGGER.debug(
        f'Checking CORS headers in {cloud} cloud '
        f'for {url} with location {location}'
    )
    resp: httpx.Response = httpx.options(
        url, verify=False, headers=request_headers
    )
    testcase.assertEqual(resp.status_code, 200)

    testcase.assertEqual(
        resp.headers['access-control-allow-methods'],
        'DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT'
    )
    testcase.assertEqual(resp.headers['access-control-max-age'], '86400')

    testcase.assertEqual(
        resp.headers['access-control-allow-credentials'], 'true'
    )

    # This test case passes only because we're testing against nginx/angie
    # starlette.middleware.cors.CORSMiddleware doesn't return this header
    testcase.assertEqual(resp.headers['access-control-allow-origin'], location)
    testcase.assertEqual(
        resp.headers['access-control-allow-headers'], 'content-type'
    )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
