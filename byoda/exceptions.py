'''
Exceptions that log messages

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

_LOGGER = logging.getLogger(__name__)


class ByodaException:
    '''
    Base class for Byoda exceptions
    '''
    def __init__(self, message, loglevel=logging.DEBUG):
        logging.log(level=loglevel, msg=message)
        super().__init__(message)


class ByodaValueError(ByodaException, ValueError):
    def __init__(self, message, loglevel=logging.DEBUG):
        ByodaException.__init__(self, message, loglevel)
        ValueError.__init__(message)


class ByodaMissingAuthInfo(ByodaException):
    def __init__(self, message, loglevel=logging.DEBUG):
        ByodaException.__init__(self, message, loglevel)
        ValueError.__init__(message)


class PodInvalidAuthInfo(Exception):
    pass


class PodIncorrectAuthInfo(Exception):
    pass
