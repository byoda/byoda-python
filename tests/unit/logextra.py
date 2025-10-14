#!/usr/bin/env python3

import sys

from logging import Logger

from byoda.util.logger import Logger as ByodaLogger

_LOGGER = None


def main() -> None:
    _LOGGER.debug('debug message', extra={'extra': 'extra_value'})


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=True
    )

    main()