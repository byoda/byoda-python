'''
Schema for server to server APIs

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class LetsEncryptSecretModel(BaseModel):
    secret: str
