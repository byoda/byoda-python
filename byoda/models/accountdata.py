'''
API models for MemberData

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from logging import getLogger
from byoda.util.logger import Logger

from pydantic import BaseModel

_LOGGER: Logger = getLogger(__name__)


class AccountDataDownloadResponseModel(BaseModel):
    data: dict

    def __repr__(self):
        return ('<AccountDataDownloadResponseModel={data: dict}>')

    def as_dict(self):
        return {'data': self.data}
