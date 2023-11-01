'''
Test cases for Query ID cache

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import yaml
import shutil
import unittest

from uuid import UUID
from datetime import datetime
from datetime import timezone

from byoda.util.logger import Logger

from byoda.datacache.om_redis import OMRedis

from svcserver.asset_model import Asset
from svcserver.asset_model import Video_chapter
from svcserver.asset_model import Video_thumbnail
from svcserver.asset_model import Claim

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import get_test_uuid

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

TEST_DIR = '/tmp/byoda-tests/assetdb'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)

        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

    @classmethod
    async def asyncTearDown(self):
        pass

    async def test_asset_pydantic_models(self):
        # network_data = await setup_network(TEST_DIR)
        # pod_account = await setup_account(network_data)
        # member: Member = pod_account.memberships[ADDRESSBOOK_SERVICE_ID]

        thumbnail_id: UUID = get_test_uuid()
        thumbnail = Video_thumbnail(
            thumbnail_id=thumbnail_id, width=640, height=480, size='640x480',
            preference='default', url='https://thumbnail_url',
        )
        thumbnail_str: str = str(thumbnail)
        thumbnail_model: Video_thumbnail = thumbnail.from_str(thumbnail_str)
        self.assertEqual(thumbnail, thumbnail_model)

        chapter_id: UUID = get_test_uuid()
        chapter = Video_chapter(
            chapter_id=chapter_id, start=0.0, end=10.0, title='chapter',
        )
        chapter_str: str = str(chapter)
        chapter_model: Video_chapter = chapter.from_str(chapter_str)
        self.assertEqual(chapter, chapter_model)

        claim_id: UUID = get_test_uuid()
        claim = Claim(
            claim_id=claim_id, cert_expiration=datetime.now(tz=timezone.utc),
            cert_fingerprint='claim_fingerprint', issuer_id=get_test_uuid(),
            issuer_type='app', keyfield='asset_id', keyfield_id=get_test_uuid(),
            object_fields=['blah', 'blah2'], object_type='public_assets',
            requester_id=get_test_uuid(), requester_type='member',
            signature='blah', signature_format_version='1.0.0',
            signature_timestamp=datetime.now(tz=timezone.utc),
            signature_url='https://signature_url',
            renewal_url='https://renewal_url',
            confirmation_url='https://confirmation_url',
            claims=['claim1', 'claim2', 'claim3']
        )
        claim_str: str = str(claim)
        claim_model: Claim = claim.from_str(claim_str)
        self.assertEqual(claim, claim_model)

    async def test_asset_redis_storage(self):
        config_file = os.environ.get('CONFIG_FILE', 'tests/collateral/config.yml')
        with open(config_file) as file_desc:
            config = yaml.safe_load(file_desc)

        omr = await OMRedis.setup(config['svcserver']['cache'])
        
        await omr.close()
        print('hoi')


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
