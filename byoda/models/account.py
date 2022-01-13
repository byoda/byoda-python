'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import List
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel

from byoda.datatypes import CloudType

_LOGGER = logging.getLogger(__name__)


class AccountResponseModel(BaseModel):
    account_id: UUID
    network: str
    started: datetime
    cloud: CloudType
    private_bucket: str
    public_bucket: str
    root_directory: str
    loglevel: str
    private_key_secret: str
    bootstrap: bool
    services: List
    # TODO: provide full typing for services
