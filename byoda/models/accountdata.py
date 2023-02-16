'''
API models for MemberData

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class AccountDataDownloadResponseModel(BaseModel):
    data: dict

    def __repr__(self):
        return ('<AccountDataDownloadResponseModel={data: dict}>')

    def as_dict(self):
        return {'data': self.data}
