'''
API models for IP Addresses

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from uuid import UUID

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


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

    def __repr__(self):
        return('<MemberResponseModel={service_id: int, version: int}>')

    def as_dict(self):
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

    def __repr__(self):
        return(
            '<MemberRequestModel={service_id: int, version: int}>'
        )

    def as_dict(self):
        return {
            'service_id': self.service_id,
            'verion:': self.version
        }
