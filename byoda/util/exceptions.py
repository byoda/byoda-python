'''
Exceptions that log messages

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

_LOGGER = logging.getLogger(__name__)


class ValueErrorLog(ValueError):
    def __init__(self, message, loglevel=logging.ERROR, exc_info=True):
        super().__init__(message)
        _LOGGER.log(loglevel, message, exc_info=exc_info)
