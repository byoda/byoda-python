'''
Exceptions that log messages

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

_LOGGER = logging.getLogger(__name__)


class MissingAuthInfo(Exception):
    pass


class InvalidAuthInfo(Exception):
    pass


class IncorrectAuthInfo(Exception):
    pass