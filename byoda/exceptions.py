'''
Exceptions that log messages

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

_LOGGER = logging.getLogger(__name__)


class NoAuthInfo(Exception):
    pass
