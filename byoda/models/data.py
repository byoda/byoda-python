'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class DataRequest():
    def __init__(self, member_id, service_id, request_spec):
        self.member_id = member_id
        self.service_id = service_id
        self.request_spec = request_spec

    def __repr__(self):
        return (
            f'<Data(member_id={self.member_id},service_id={self.service_id},'
            f'request_spec={self.request_spec})>'
        )

    def as_dict(self):
        return {
            'member_id': self.member_id,
            'service_id': self.service_id,
            'request_spec': self.request_spec,
        }


class DataResponseModel(BaseModel):
    member_id: UUID
    service_id: int
    data: dict
    stats: dict
