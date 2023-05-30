'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from pydantic import BaseModel


class ContentKeyResponseModel(BaseModel):
    key_id: int
    content_token: str

    def __repr__(self):
        return ('<ContentToken=(key_id: int, content_token: str)>')

    def as_dict(self):
        return {
            'key_id': self.key_id,
            'content_token': self.content_token
        }
