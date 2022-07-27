'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import Optional

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class AuthRequestModel(BaseModel):
    username: str
    password: str
    service_id: Optional[int] = None

    def __repr__(self):
        return ('<Auth=(username: str, password: str, service_id: int)>')

    def as_dict(self):
        return {
            'username': self.username,
            'password': self.password,
            'service_id': self.service_id,
        }


class AuthTokenResponseModel(BaseModel):
    auth_token: str

    def __repr__(self):
        return ('<AuthToken=(auth_token: str)>')

    def as_dict(self):
        return {'auth_token': self.auth_token}
