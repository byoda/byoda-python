'''
Exceptions that log messages

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import logging
from logging import getLogger
from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)


class ByodaException(BaseException):
    '''
    Base class for Byoda exceptions
    '''
    def __init__(self, message, loglevel=logging.DEBUG):
        logging.log(level=loglevel, msg=message)
        super().__init__(message)


class ByodaValueError(ByodaException, ValueError):
    def __init__(self, message, loglevel=logging.DEBUG):
        super(ByodaException, self).__init__(message, loglevel)
        super(ValueError, self).__init__(message)


class ByodaRuntimeError(ByodaException, RuntimeError):
    def __init__(self, message, loglevel=logging.DEBUG):
        super(ByodaException, self).__init__(message, loglevel)
        super(RuntimeError, self).__init__(message)


class ByodaMissingAuthInfo(ByodaException):
    def __init__(self, message, loglevel=logging.DEBUG):
        super().__init__(message, loglevel)


class ByodaDataClassReferenceNotFound(ByodaException):
    def __init__(self, message, loglevel=logging.DEBUG):
        super().__init__(message, loglevel)


class PodInvalidAuthInfo(BaseException):
    pass


class PodIncorrectAuthInfo(BaseException):
    pass
