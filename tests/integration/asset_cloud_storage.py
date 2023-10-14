#!/usr/bin/env python3

'''
Test cloud storage

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import sys
import unittest

from urllib.parse import urlparse, ParseResult

import requests
from byoda.util.logger import Logger

from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import AZURE_RESTRICTED_BUCKET_FILE
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

TEST_DIR = '/tmp/byoda-tests/cloud_assets'

ASSET_FILE: str = 'tests/collateral/azure_assets.out'


class TestAssetStorage(unittest.IsolatedAsyncioTestCase):
    async def test_azure_assets(self):
        with open(ASSET_FILE) as file_desc:
            for line in file_desc.readlines():
                youtube_id, url = line.strip().split('|', 2)

                parsed_url: ParseResult = urlparse(url)
                service_id, member_id, asset_id, filename = \
                    parsed_url.path.split('/')[2:6]

                self.assertEqual(member_id, AZURE_POD_MEMBER_ID)
                self.assertEqual(service_id, str(ADDRESSBOOK_SERVICE_ID))

                with open(AZURE_RESTRICTED_BUCKET_FILE) as file_desc:
                    restricted_bucket = file_desc.read().strip()

                account, container = restricted_bucket.split(':', 2)
                cloud_url = (
                    f'https://{account}.blob.core.windows.net/{container}'
                    f'/{asset_id}/{filename}'
                )
                resp = requests.head(cloud_url)
                print(f'{resp.status_code} - {cloud_url}')
                self.assertEqual(resp.status_code, 200)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
