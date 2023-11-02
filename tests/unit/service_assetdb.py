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

from datetime import datetime
from datetime import timezone

# from byoda.datamodel.member import Member
from byoda.datatypes import DataRequestType

from byoda.datacache.om_redis import OMRedis

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from svcserver.asset_model import Asset
from svcserver.asset_model import Video_chapter
from svcserver.asset_model import Video_thumbnail
from svcserver.asset_model import Claim
from svcserver.asset_model import Monetization

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

    async def test_asset_redis_storage(self):
        # network_data = await setup_network(TEST_DIR)
        # pod_account = await setup_account(network_data)
        # member: Member = pod_account.memberships[ADDRESSBOOK_SERVICE_ID]

        config_file = os.environ.get('CONFIG_FILE', 'config.yml')
        with open(config_file) as file_desc:
            config = yaml.safe_load(file_desc)

        omr = await OMRedis.setup(config['svcserver']['cache'])

        service_id: int = ADDRESSBOOK_SERVICE_ID

        data = get_asset()
        omr.add_model(Asset)
        await data.save()
        claim: Asset = await Asset.get(data.asset_id)

        self.assertEqual(data.created_timestamp, claim.created_timestamp)

        resp: HttpResponse = await DataApiClient.call(
            service_id, 'public_assets', action=DataRequestType.QUERY,
            custom_domain='azure.byoda.me', network='byoda.net',
        )

        await omr.close()

        print('hoi')


def get_asset() -> dict[str, object]:
    thumbnail_1 = Video_thumbnail(
        thumbnail_id=str(get_test_uuid()), width=640, height=480,
        size='640x480', preference='default', url='https://thumbnail_url',
    )
    thumbnail_2 = Video_thumbnail(
        thumbnail_id=str(get_test_uuid()), width=320, height=2480,
        size='320x240', preference='default', url='https://thumbnail2_url',
    )

    chapter_1 = Video_chapter(
        chapter_id=str(get_test_uuid()), start=0.0, end=10.0, title='chapter',
    )

    chapter_2 = Video_chapter(
        chapter_id=str(get_test_uuid()), start=0.0, end=10.0, title='chapter',
    )

    claim_1 = Claim(
        claim_id=str(get_test_uuid()),
        cert_expiration=datetime.now(tz=timezone.utc).isoformat(),
        cert_fingerprint='claim1_fingerprint',
        issuer_id=str(get_test_uuid()),
        issuer_type='app', keyfield='asset_id',
        requester_id=str(get_test_uuid()), requester_type='member',
        signature='blah', signature_format_version='1.0.0',
        signature_timestamp=datetime.now(tz=timezone.utc).isoformat(),
        signature_url='https://signature_url',
        renewal_url='https://renewal_url',
        confirmation_url='https://confirmation_url',
        claims=['claim11', 'claim12', 'claim13']
    )

    claim_2 = Claim(
        claim_id=str(get_test_uuid()),
        cert_expiration=datetime.now(tz=timezone.utc).isoformat(),
        cert_fingerprint='claim2_fingerprint',
        issuer_id=str(get_test_uuid()),
        issuer_type='app', keyfield='asset_id',
        object_fields=['blah2', 'blah22'], object_type='public_assets',
        requester_id=str(get_test_uuid()), requester_type='member',
        signature='blah', signature_format_version='1.0.0',
        signature_timestamp=datetime.now(tz=timezone.utc).isoformat(),
        signature_url='https://signature2_url',
        renewal_url='https://renewal2_url',
        confirmation_url='https://confirmation2_url',
        claims=['claim21', 'claim22', 'claim23']
    )

    monetization_1 = Monetization(
        monetization_id=str(get_test_uuid()),
        monetization_scheme='free'
    )

    asset = Asset(
        asset_id=get_test_uuid(), asset_type='video',
        created_timestamp=datetime.now(tz=timezone.utc),
        asset_merkle_root_hash='1',
        asset_url='https://asset_url',
        channel_id=get_test_uuid(),
        content_warnings=['warning1', 'warning2'],
        contents='contents',
        copyright_years=[102, 1492],
        creator='byoda',
        ingest_status='published',
        publisher_timestamp=datetime.now(tz=timezone.utc),
        publisher='byoda',
        publisher_asset_id='byoda',
        screen_orientation_horizontal=True,
        title='asset', subject='asset',
        _meta_member_id=get_test_uuid(),
        _meta_last_updated=datetime.now(tz=timezone.utc),
        video_thumbnails=[thumbnail_1, thumbnail_2],
        video_chapters=[chapter_1, chapter_2],
        claims=[claim_1, claim_2],
        monetizations=[monetization_1]
    )
    return asset


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
