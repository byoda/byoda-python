'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class LetsEncryptSecretModel(BaseModel):
    secret: str
