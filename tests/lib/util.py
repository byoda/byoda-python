'''
Helper functions for tests

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

from uuid import UUID
from uuid import uuid4
from datetime import datetime
from datetime import timezone

from fastapi import FastAPI

from byoda.datamodel.network import Network
from byoda.datamodel.member import Member

from byoda.datatypes import DataRequestType
from byoda.datatypes import DataFilterType

from byoda.util.api_client.data_api_client import DataApiClient

from podserver.codegen.pydantic_service_4294929430_1 import (
    asset as Asset,
    video_chapter as Video_chapter,
    video_thumbnail as Video_thumbnail,
    claim as Claim,
    monetization as Monetization
)

TEST_ASSET_ID: UUID = '32af2122-4bab-40bb-99cb-4f696da49e26'


def get_test_uuid() -> UUID:
    id = str(uuid4())
    id = 'aaaaaaaa' + id[8:]
    id = UUID(id)
    return id


def get_account_tls_headers(account_id: UUID, network: str) -> dict:
    account_headers = {
        'X-Client-SSL-Verify': 'SUCCESS',
        'X-Client-SSL-Subject':
            f'CN={account_id}.accounts.{network}',
        'X-Client-SSL-Issuing-CA': f'CN=accounts-ca.{network}'
    }
    return account_headers


def get_member_tls_headers(member_id: UUID, network: str | Network,
                           service_id: int) -> dict:
    if isinstance(network, Network):
        network = network.name

    member_headers = {
        'X-Client-SSL-Verify': 'SUCCESS',
        'X-Client-SSL-Subject':
            f'CN={member_id}.members-{service_id}.{network}',
        'X-Client-SSL-Issuing-CA': f'CN=members-ca.{network}'
    }
    return member_headers


async def call_data_api(service_id: int, class_name: str,
                        action: DataRequestType = DataRequestType.QUERY,
                        first: int | None = None, after: str | None = None,
                        depth: int = 0, fields: set[str] | None = None,
                        data_filter: DataFilterType | None = None,
                        data: dict[str, object] | None = None,
                        auth_header: str = None, expect_success: bool = True,
                        app: FastAPI = None, test=None, internal: bool = True,
                        member: Member | None = None
                        ) -> dict[str, object] | int | None:
    '''
    Wrapper for REST Data API for test cases

    :param service_id:
    :param class_name:
    :param action:
    :param first:
    :param after:
    :param depth:
    :param fields:
    :param data_filter:
    :param data:
    :param auth_header:
    :param expect_success: should the HTTP status code match '200'
    :param test: unittest.TestCase
    :returns:
    :raises:
    '''

    member_id: UUID | None = None
    if member:
        member_id = member.member_id

    resp = await DataApiClient.call(
        service_id=service_id, class_name=class_name, action=action,
        first=first, after=after, depth=depth, fields=fields,
        data_filter=data_filter, data=data, member_id=member_id,
        headers=auth_header, app=app, internal=internal
    )

    if test and expect_success:
        test.assertEqual(resp.status_code, 200)

    result: dict = resp.json()

    if not expect_success or not test:
        return result

    if action == DataRequestType.QUERY:
        test.assertIsNotNone(result['total_count'])
    elif action in (DataRequestType.APPEND, DataRequestType.DELETE):
        test.assertIsNotNone(result)
        test.assertGreater(result, 0)
    else:
        pass

    return result


def get_asset(asset_id: str = TEST_ASSET_ID) -> dict[str, object]:
    '''
    Creates and returns an asset object with dummy data.
    '''

    if not asset_id:
        asset_id = get_test_uuid()
    if not isinstance(asset_id, UUID):
        asset_id = UUID(asset_id)

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
        keyfield_id=str(asset_id),
        object_fields=['blah1', 'blah12'], object_type='public_assets',
        signature='blah', signature_format_version=1,
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
        keyfield_id=str(asset_id),
        object_fields=['blah2', 'blah22'], object_type='public_assets',
        requester_id=str(get_test_uuid()), requester_type='member',
        signature='blah', signature_format_version=1,
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
        asset_id=asset_id, asset_type='video',
        created_timestamp=datetime.now(tz=timezone.utc),
        asset_merkle_root_hash='1',
        asset_url='https://asset_url',
        channel_id=get_test_uuid(),
        content_warnings=['warning1', 'warning2'],
        contents='contents',
        copyright_years=[102, 1492],
        creator='byoda',
        ingest_status='published',
        published_timestamp=datetime.now(tz=timezone.utc),
        publisher='byoda',
        publisher_asset_id='byoda',
        screen_orientation_horizontal=True,
        title='asset', subject='asset',
        video_thumbnails=[thumbnail_1, thumbnail_2],
        video_chapters=[chapter_1, chapter_2],
        claims=[claim_1, claim_2],
        monetizations=[monetization_1]
    )
    return asset
