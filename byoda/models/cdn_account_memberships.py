'''
Schema for pod to report its memberships to the CDN

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from typing import LiteralString

from pydantic import BaseModel


class CdnAccountMembershipsRequestModel(BaseModel):
    container: str
    account: UUID
    membership_id: UUID
    service_id: int

    def __repr__(self) -> LiteralString:
        return (
            '<CdnAccountMembershipsRequestModel='
            '(account_id: UUID, membership_ids: list[UUID]>'
        )

    def as_dict(self) -> dict[str, UUID | list[UUID]]:
        return {
            'account_id': self.account_id,
            'membership_ids': self.membership_ids
        }
