'''
Exceptions that log messages

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import logging
from logging import Logger
from logging import getLogger

_LOGGER: Logger = getLogger(__name__)


class ByodaException(Exception):
    '''
    Base class for Byoda exceptions
    '''
    def __init__(self, message, loglevel=logging.DEBUG,
                 extra: dict[str, any] = {}) -> None:
        _LOGGER.log(
            level=loglevel, msg=message,
            extra=extra | {'exception': {str(self)}}
        )
        super().__init__(message)


class ByodaValueError(ByodaException, ValueError):
    def __init__(self, message, loglevel=logging.DEBUG,
                 extra: dict[str, any] = {}) -> None:
        super().__init__(message, loglevel, extra=extra)


class ByodaRuntimeError(ByodaException, RuntimeError):
    def __init__(self, message, loglevel=logging.DEBUG,
                 extra: dict[str, any] = {}) -> None:
        super().__init__(message, loglevel, extra=extra)


class ByodaMissingAuthInfo(ByodaException):
    def __init__(self, message, loglevel=logging.DEBUG,
                 extra: dict[str, any] = {}) -> None:
        super().__init__(message, loglevel, extra=extra)


class ByodaDataClassReferenceNotFound(ByodaException):
    def __init__(self, message, loglevel=logging.DEBUG,
                 extra: dict[str, any] = {}) -> None:
        super().__init__(message, loglevel, extra=extra)


class PodInvalidAuthInfo(BaseException):
    pass


class PodIncorrectAuthInfo(BaseException):
    pass
