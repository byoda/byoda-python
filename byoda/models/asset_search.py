'''
Schema for asset search API

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger

from pydantic import BaseModel

_LOGGER: Logger = getLogger(__name__)


class AssetSearchRequestModel(BaseModel):
    hashtags: list[str] | None = None
    mentions: list[str] = None
    nickname: str | None = None
    text: str | None = None
    asset_id: UUID | None = None

    def __repr__(self):
        return ('<AssetSearch=(hashtag: str, handle: str, text: str)>')


class AssetSubmitRequestModel(BaseModel):
    hashtags: list[str] | None
    mentions: list[str] | None
    nickname: str | None
    text: str | None
    asset_id: str

    def __repr__(self):
        return (
            '<AssetSubmit=(hashtag: str, handle: str, text: str, handle: str, '
            'asset_id: str)>'
        )


class AssetSearchResultsResponseModel(BaseModel):
    member_id: UUID
    asset_id: str

    def __repr__(self):
        return ('<AssetSearchResults=(member_id: UUID, asset_id: str)>')
