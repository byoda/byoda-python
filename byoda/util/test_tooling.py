'''
Tools for test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from uuid import UUID
from logging import getLogger

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)

UUID_TEST_MARKER: str = 'aaaaaaaa'


def is_test_uuid(uuid: UUID | str) -> bool:
    return str(uuid).lower().startswith(UUID_TEST_MARKER)


def convert_number_string(number_text: str | int) -> int | None:
    '''
    Converts a number with optional appendix of m, k, to an integer
    '''

    if not number_text or isinstance(number_text, int):
        return number_text

    words: list[str] = number_text.split(' ')
    number_text = words[0].strip()

    try:
        multiplier: str = number_text[-1].upper()
        if not multiplier.isnumeric():
            multipliers: dict[str, int] = {
                'K': 1000,
                'M': 1000000,
                'B': 1000000000,
            }
            count_pre: float = float(number_text[:-1])
            count = int(
                count_pre * multipliers[multiplier]
            )
        else:
            count = int(number_text)

        return count
    except Exception as exc:
        _LOGGER.debug(
            f'Could not convert text {number_text} to a number: {exc}'
        )

        return None
