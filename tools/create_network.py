#!/usr/bin/env python3

'''
Creates certitificates:
- root CA
- accounts CA
- services CA

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import sys
import os
import shutil
import asyncio
import argparse
from logging import Logger

from byoda.datamodel.network import Network

from byoda.util.logger import Logger as ByodaLogger

_LOGGER: Logger | None = None

_ROOT_DIR: str = os.environ['HOME'] + '/.byoda'


async def main(argv) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument('--network', '-n', type=str, default='testdomain.com')
    parser.add_argument('--root-directory', '-r', type=str, default=_ROOT_DIR)
    parser.add_argument('--password', '-p', type=str, default='byoda')
    args: argparse.Namespace = parser.parse_args()

    global _LOGGER
    _LOGGER = ByodaLogger.getLogger(
        argv[0], debug=args.debug, verbose=args.verbose,
        json_out=False
    )

    root_dir: str = args.root_directory
    if root_dir.startswith('/tmp') and os.path.exists(root_dir):
        _LOGGER.debug(f'Wiping temporary root directory: {root_dir}')
        shutil.rmtree(root_dir)

    _LOGGER.debug(
        f'Creating root CA cert and private key under {args.root_directory}'
    )
    await Network.create(args.network, root_dir, args.password, renew=True)


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
