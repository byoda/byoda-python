'''
Models for input and output of FastAPI APIs for the BYO.Tube-Lite service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import re
from uuid import UUID
from typing import Iterable
from datetime import datetime
from string import punctuation

from pydantic import BaseModel
from pydantic import field_validator
from pydantic import Field
from pydantic import EmailStr
from pydantic import ConfigDict

from profanity_check import predict

NICK_RX: re.Pattern[str] = re.compile(
    r'^[a-zA-Z0-9\-\.\$\'\(\)\/\?\[\]\{\}\"|~^<>#!%,:;_]+$'
)


class OrmBaseModel(BaseModel):
    '''
    Base model for ORM models.
    '''

    model_config = ConfigDict(from_attributes=True)


class WaitlistRequest(OrmBaseModel):
    '''
    A waitlist entry.
    '''

    email: EmailStr


class UserCreate(OrmBaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)
    nick: str = Field(min_length=5, max_length=32)
    invite_code: str = Field(min_length=6, max_length=6)

    @field_validator('password')
    def check_password(cls, value: str) -> str:
        value = value.strip()

        if not any(c.isupper() for c in value) or \
                not any(c.islower() for c in value) or \
                not any(c.isdigit() for c in value) or \
                not any(c in punctuation for c in value):
            raise ValueError(
                'Password must have at least one uppercase letter, '
                'one lowercase letter, and one digit'
            )

        return value

    @field_validator('nick')
    def check_nick(cls, value: str | None) -> str | None:
        if value:
            value = value.strip()

        result: Iterable[int] = predict([value])
        if len(result) > 0 and result[0] == 1:
            raise ValueError('Nick is deemed to contain profanity')

        if not NICK_RX.match(value):
            raise ValueError(
                'Nick must contain only letters between a and z or A and Z,'
                'digits, and the following characters: '
                '-.$\'()/?[]{}"|~^<>#!%,:;_'
            )
        return value


class UserResponse(OrmBaseModel):
    '''
    The response for the /me API.
    '''

    email: EmailStr
    is_enabled: bool


class User(UserResponse):
    user_id: int
    hashed_password: str | None = None


class UserCreateResponse(BaseModel):
    '''
    The response for the /user API.
    '''

    email: EmailStr
    account_id: UUID
    pod_account_id: UUID
    jwt: str
    jwt_type: str = 'Bearer'


class AccountInvite(OrmBaseModel):
    invite_id: int
    email: EmailStr
    invite_code: str
    account_id: int | None = None


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class ProvisioningResponse(BaseModel):
    timestamp: datetime
    completed_percentage: int
    status: str


class AccountResponse(BaseModel):
    id: int
    pod_account_id: UUID
    is_active: bool
    pod_account_password: str
    private_key_password: str
    sku: str
    youtube_channel: str | None
    youtube_ingest_streams: str | None
    custom_domain: str | None

