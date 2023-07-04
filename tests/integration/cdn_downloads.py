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

# flake8: noqa=E501

import sys
import unittest

from uuid import uuid4, UUID

import requests

from byoda.util.logger import Logger

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.defines import AZURE_POD_MEMBER_FQDN
from tests.lib.defines import AWS_POD_MEMBER_FQDN
from tests.lib.defines import GCP_POD_MEMBER_FQDN
from tests.lib.defines import HOME_POD_MEMBER_FQDN
from tests.lib.defines import AZURE_POD_CUSTOM_DOMAIN
from tests.lib.defines import AWS_POD_CUSTOM_DOMAIN
from tests.lib.defines import GCP_POD_CUSTOM_DOMAIN
from tests.lib.defines import HOME_POD_CUSTOM_DOMAIN

from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import AWS_POD_MEMBER_ID
from tests.lib.defines import GCP_POD_MEMBER_ID
from tests.lib.defines import HOME_POD_MEMBER_ID

_LOGGER = None

TEST_DIR = '/tmp/byoda-tests/proxy_test'

URLS: dict[str, dict[str, str]] = {
    'azure': {
        'storage': {
            'restricted': 'https://byodaprivate.blob.core.windows.net/restricted-xjfwiq/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': 'https://byodaprivate.blob.core.windows.net/public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html'
        },
        'pod-member': {
            'restricted': f'https://{AZURE_POD_MEMBER_FQDN}/restricted/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://{AZURE_POD_MEMBER_FQDN}/public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'pod-custom': {
            'restricted': f'https://{AZURE_POD_CUSTOM_DOMAIN}/restricted/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://{AZURE_POD_CUSTOM_DOMAIN}/public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'cdn': {
            'restricted': f'https://cdn.byoda.io/restricted/{ADDRESSBOOK_SERVICE_ID}/{AZURE_POD_MEMBER_ID}/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://cdn.byoda.io/public/{ADDRESSBOOK_SERVICE_ID}/{AZURE_POD_MEMBER_ID}/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
    },
    'aws': {
        'storage': {
            'restricted': 'https://byoda-restricted-000d3a3b236d.s3.us-east-2.amazonaws.com/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': 'https://byoda-public.s3.us-east-2.amazonaws.com/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'pod-member': {
            'restricted': f'https://{AWS_POD_MEMBER_FQDN}/restricted/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://{AWS_POD_MEMBER_FQDN}/public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'pod-custom': {
            'restricted': f'https://{AWS_POD_CUSTOM_DOMAIN}/restricted/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://{AWS_POD_CUSTOM_DOMAIN}/public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'cdn': {
            'restricted': f'https://cdn.byoda.io/restricted/{ADDRESSBOOK_SERVICE_ID}/{AWS_POD_MEMBER_ID}/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://cdn.byoda.io/public/{ADDRESSBOOK_SERVICE_ID}/{AWS_POD_MEMBER_ID}/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
    },
    'gcp': {
        'storage': {
            'restricted': 'https://storage.googleapis.com/byoda-restricted-00155daaf7ad/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': 'https://storage.googleapis.com/byoda-public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'pod-member': {
            'restricted': f'https://{GCP_POD_MEMBER_FQDN}/restricted/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://{GCP_POD_MEMBER_FQDN}/public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'pod-custom': {
            'restricted': f'https://{GCP_POD_CUSTOM_DOMAIN}/restricted/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://{GCP_POD_CUSTOM_DOMAIN}/public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'cdn': {
            'restricted': f'https://cdn.byoda.io/restricted/{ADDRESSBOOK_SERVICE_ID}/{GCP_POD_MEMBER_ID}/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://cdn.byoda.io/public/{ADDRESSBOOK_SERVICE_ID}/{GCP_POD_MEMBER_ID}/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
    },
    'local': {
        'pod-member': {
            'restricted': f'https://{HOME_POD_MEMBER_FQDN}/restricted/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://{HOME_POD_MEMBER_FQDN}/public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'pod-custom': {
            'restricted': f'https://{HOME_POD_CUSTOM_DOMAIN}/restricted/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://{HOME_POD_CUSTOM_DOMAIN}/public/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',
        },
        'cdn': {
            'restricted': f'https://cdn.byoda.io/restricted/{ADDRESSBOOK_SERVICE_ID}/{HOME_POD_MEMBER_ID}/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/restricted.html',
            'public': f'https://cdn.byoda.io/public/{ADDRESSBOOK_SERVICE_ID}/{HOME_POD_MEMBER_ID}/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/public.html',

        },

    }
}

MEMBER_IDS: dict[str, str] = {
    'azure': AZURE_POD_MEMBER_ID,
    'aws': AWS_POD_MEMBER_ID,
    'gcp': GCP_POD_MEMBER_ID,
    'local': HOME_POD_MEMBER_ID,
}


class TestWebServer(unittest.TestCase):
    def test_html_file(self):
        for cloud in URLS:
            if cloud == 'local':
                continue

            for target in URLS[cloud]:
                if target == 'pod-member':
                    ssl_root = \
                        'tests/collateral/network-byoda.net-root-ca-cert.pem'
                else:
                    ssl_root = None

                for access, url in URLS[cloud][target].items():
                    if access != 'restricted' or 'byoda.' not in url:
                        _LOGGER.debug(
                            f'Testing for target {target} {access} access '
                            f'for cloud {cloud}: url={url}'
                        )
                        response = requests.get(url, verify=ssl_root)
                        self.assertEqual(response.status_code, 200)
                    else:
                        _LOGGER.debug(
                            f'Testing for target {target} {access} access '
                            f'for cloud {cloud}: url={url}'
                        )
                        response = requests.get(url, verify=ssl_root)
                        # Disabled while content_token is disabled
                        # self.assertEqual(response.status_code, 403)
                        self.assertEqual(response.status_code, 200)

                        asset_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
                        key_id, token = get_token(url, asset_id, cloud)
                        response = requests.get(
                            url, verify=ssl_root,
                            headers={'Authorization': f'Bearer {token}'},
                            params={
                                'key_id': key_id,
                                'service_id': ADDRESSBOOK_SERVICE_ID,
                                'asset_id': str(asset_id),
                                'member_id': MEMBER_IDS[cloud],

                            }
                        )
                        self.assertEqual(response.status_code, 200)

    def test_content_token(self):
        base_url = 'https://azure.byoda.me/api/v1/pod/content/token'
        url = base_url + '?' + '&'.join(
            [
                f'service_id={ADDRESSBOOK_SERVICE_ID}',
                f'asset_id={uuid4()}',
                f'signedby={uuid4()}',
                'token=blah'
            ]
        )
        response = requests.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNotNone(data.get('content_token'))
        self.assertIsNotNone(data.get('key_id'))


def get_token(url: str, asset_id: UUID, cloud: str) -> tuple[int, str]:
    url = (
        f'https://{MEMBER_IDS[cloud]}.'
        f'members-{ADDRESSBOOK_SERVICE_ID}.byoda.net/api/v1/pod/content/token'
    )
    query_params = {
        'asset_id': str(asset_id),
        'service_id': ADDRESSBOOK_SERVICE_ID,
        'signedby': str(uuid4()),
        'token': 'placeholder'
    }

    try:
        result = requests.get(
            url, params=query_params,
            verify='tests/collateral/network-byoda.net-root-ca-cert.pem'
        )
    except urllib3.exceptions.ConnectionTimeoutError:
        if cloud != 'local':
            raise

    data = result.json()
    key_id: int = data.get('key_id')
    token: str = data.get('content_token')

    return (key_id, token)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
