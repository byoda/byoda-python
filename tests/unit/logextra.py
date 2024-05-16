#!/usr/bin/env python3

import sys

from byoda.util.logger import Logger

_LOGGER = None


def main() -> None:
    _LOGGER.debug('debug message', extra={'extra': 'extra_value'})


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=True)

    main()