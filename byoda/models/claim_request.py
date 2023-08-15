'''
Schema for requesting claims

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from uuid import UUID
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from byoda.datatypes import ClaimStatus
from byoda.datatypes import IdType

_LOGGER = logging.getLogger(__name__)


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


class ClaimResponseModel(BaseModel):
    status: ClaimStatus
    request_id: UUID
    signature: Optional[str] | None = None
    signature_timestamp: Optional[datetime] | None = None
    issuer_type: Optional[IdType] | None = None
    issuer_id: Optional[UUID] | None = None
    cert_fingerprint: Optional[str] | None = None
    cert_expiration: Optional[datetime] | None = None

    def __repr__(self):
        return (
            '<ClaimResponse=(request_id: UUID, '
            'claim_status: ClaimStatus, '
            'claim_signature: str | None>'
        )
