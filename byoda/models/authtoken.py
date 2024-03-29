'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger

from pydantic import BaseModel

from byoda.datatypes import IdType

_LOGGER: Logger = getLogger(__name__)


class AuthRequestModel(BaseModel):
    username: str
    password: str
    target_type: IdType = IdType.MEMBER
    app_id: UUID | None = None
    service_id: int | None = None

    def __repr__(self):
        return ('<Auth=(username: str, password: str, service_id: int)>')

    def as_dict(self):
        return {
            'username': self.username,
            'password': self.password,
            'service_id': self.service_id,
            'app_id': self.app_id,
        }


class AuthTokenResponseModel(BaseModel):
    auth_token: str

    def __repr__(self):
        return ('<AuthToken=(auth_token: str)>')

    def as_dict(self):
        return {'auth_token': self.auth_token}
