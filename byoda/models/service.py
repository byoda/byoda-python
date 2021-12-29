'''
API models for IP Addresses

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from pydantic import BaseModel
from typing import Optional, List

_LOGGER = logging.getLogger(__name__)


class ServiceSummaryResponseModel(BaseModel):
    service_id: int
    version: int
    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    supportemail: Optional[str] = None

    def __repr__(self):
        return('<ServiceSummaryResponseModel)={ServiceId: str}>')

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
    service_summaries: List[ServiceSummaryResponseModel]

    def __repr__(self):
        return(
            '<ServiceSummariesModel='
            '{List[ServiceSummaryResponseModel]}>'
        )

    def as_dict(self):
        return self.service_summaries
