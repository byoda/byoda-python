'''
API models for IP Addresses

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from uuid import UUID
from logging import Logger
from logging import getLogger
from typing import LiteralString

from pydantic import BaseModel

_LOGGER: Logger = getLogger(__name__)


class MemberResponseModel(BaseModel):
    account_id: UUID
    network: str
    member_id: UUID
    service_id: int
    version: int
    name: str
    owner: str
    website: str
    supportemail: str
    description: str
    certificate: str
    private_key: str

    def __repr__(self) -> LiteralString:
        return ('<MemberResponseModel={service_id: int, version: int}>')

    def as_dict(self) -> dict[str, UUID | str | int]:
        return {
            'account_id': self.account_id,
            'network': self.network,
            'member_id': self.member_id,
            'service_id': self.service_id,
            'version': self.version,
            'name': self.name,
            'owner': self.owner,
            'website': self.website,
            'description': self.description,
            'supportemail': self.supportemail,
            'certificate': self.certificate,
            'private_key': self.private_key,
        }


class MemberRequestModel(BaseModel):
    service_id: int
    version: int

    def __repr__(self) -> LiteralString:
        return (
            '<MemberRequestModel={service_id: int, version: int}>'
        )

    def as_dict(self) -> dict[str, int]:
        return {
            'service_id': self.service_id,
            'version:': self.version
        }


class UploadResponseModel(BaseModel):
    service_id: int
    asset_id: UUID
    locations: list[str]
    cdn_urls: list[str]

    def __repr__(self):
        return (
            '<UploadResponseModel='
            '{service_id: int, asset_id: UUID, locations: list[str]}>'
        )

    def as_dict(self):
        return {
            'service_id': self.service_id,
            'asset_id': self.asset_id,
            'locations': self.locations,
            'cdn_urls': self.cdn_urls

        }
