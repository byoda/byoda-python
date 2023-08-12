'''
Schema for requesting claims

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from uuid import UUID

from pydantic import BaseModel
from pydantic import HttpUrl

from byoda.datatypes import ClaimStatus
from byoda.datatypes import IdType

_LOGGER = logging.getLogger(__name__)


class ClaimResponseModel(BaseModel):
    claim_status: ClaimStatus
    claim_signature: str | None

    def __repr__(self):
        return (
            '<ClaimResponse=(claim_status: ClaimStatus, '
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

