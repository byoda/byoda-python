'''
Schema for requesting claims

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from uuid import UUID

from pydantic import BaseModel

from byoda.datatypes import ClaimStatus

_LOGGER = logging.getLogger(__name__)


class ClaimResponseModel(BaseModel):
    status: ClaimStatus
    request_id: UUID
    signature: str | None

    def __repr__(self):
        return (
            '<ClaimResponse=(request_id: UUID, '
            'claim_status: ClaimStatus, '
            'claim_signature: str | None>'
        )


class AssetClaimDataModel(BaseModel):
    asset_id: UUID
    asset_type: str
    asset_url: str
    asset_merkle_root_hash: str
    public_video_thumbnails: list[str]
    creator: str
    publisher: str
    publisher_asset_id: str
    title: str
    contents: str
    annotations: list[str]


class AssetClaimRequestModel(BaseModel):
    claims: list[str]
    claim_data: AssetClaimDataModel

    def __repr__(self):
        return (
            '<AssetClaimRequest=(object_type: str, claims: list[str], '
            'claim_data: dict)>'
        )

