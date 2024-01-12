'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from datetime import datetime

from pydantic import BaseModel
from pydantic import Field


class ContentKeyResponseModel(BaseModel):
    key_id: int
    content_token: str

    def __repr__(self):
        return ('<ContentToken=(key_id: int, content_token: str)>')

    def as_dict(self) -> dict[str, any]:
        return {
            'key_id': self.key_id,
            'content_token': self.content_token
        }


class ContentKeyRequestModel(BaseModel):
    key_id: int = Field(gt=0)
    key: str
    not_before: datetime
    not_after: datetime

    def __repr__(self):
        return (
            '<ContentKeyRequestModel=(key_id: int, key: str, '
            'not_before: datetime, not_after: datetime)>'
        )

    def as_dict(self) -> dict[str, str | int | datetime]:
        return {
            'key_id': self.key_id,
            'key': self.key,
            'not_before': self.not_before,
            'not_after': self.not_after
        }
