'''
Tools for test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from logging import getLogger

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)

UUID_TEST_MARKER: str = 'aaaaaaaa'


def is_test_uuid(uuid: UUID | str):
    return str(uuid).lower().startswith(UUID_TEST_MARKER)
