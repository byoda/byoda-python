'''
API models for IP Addresses

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class ServiceSummaryResponseModel(BaseModel):
    service_id: int
    version: int
    name: str
    title: str | None = None
    description: str | None = None
    supportemail: str | None = None

    def __repr__(self):
        return ('<ServiceSummaryResponseModel)={ServiceId: str}>')

    def as_dict(self):
        return {
            'service_id': self.service_id,
            'version': self.version,
            'name': self.name,
            'title': self.title,
            'description': self.description,
            'supportemail': self.supportemail,
        }


class ServiceSummariesModel(BaseModel):
    service_summaries: list[ServiceSummaryResponseModel]

    def __repr__(self):
        return (
            '<ServiceSummariesModel='
            '{list[ServiceSummaryResponseModel]}>'
        )

    def as_dict(self):
        return self.service_summaries
