'''
Schema for asset search API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from uuid import UUID

from typing import Optional, List

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class AssetSearchRequestModel(BaseModel):
    hashtags: Optional[List[str]]
    mentions: Optional[List[str]]
    nickname: Optional[str]
    text: Optional[str]
    asset_id: Optional[str]

    def __repr__(self):
        return ('<AssetSearch=(hashtag: str, handle: str, text: str)>')

    def as_dict(self):
        return {
            'hashtag': self.hashtag,
        }


class AssetSubmitRequestModel(BaseModel):
    hashtags: Optional[List[str]]
    mentions: Optional[List[str]]
    nickname: Optional[str]
    text: Optional[str]
    asset_id: str

    def __repr__(self):
        return (
            '<AssetSubmit=(hashtag: str, handle: str, text: str, handle: str, '
            'asset_id: str)>'
        )

    def as_dict(self):
        return {
            'hashtag': self.hashtag,
        }


class AssetSearchResultsResponseModel(BaseModel):
    member_id: UUID
    asset_id: str

    def __repr__(self):
        return ('<AssetSearchResults=(member_id: UUID, asset_id: str)>')

    def as_dict(self):
        return {'member_id': self.member_id, 'asset_id': self.asset_id}
