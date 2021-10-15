#!/usr/bin/env python3

'''
Manages certitificates:
- create root CA for
  - account
  - service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import sys
import os
import argparse
import shutil

from byoda.util import Logger

from byoda.datamodel import Network
from byoda.util.secrets import NetworkRootCaSecret

from byoda.util import Paths


_LOGGER = None

_ROOT_DIR = os.environ['HOME'] + '/.byoda'


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument('--network', '-n', type=str, default='testdomain.com')
    parser.add_argument('--root-directory', '-r', type=str, default=_ROOT_DIR)
    parser.add_argument('--password', '-p', type=str, default='byoda')
    args = parser.parse_args()

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], debug=args.debug, verbose=args.verbose,
        json_out=False
    )

    root_dir = args.root_directory
    if root_dir.startswith('/tmp') and os.path.exists(root_dir):
        _LOGGER.debug(f'Wiping temporary root directory: {root_dir}')
        shutil.rmtree(root_dir)

    _LOGGER.debug(
        f'Creating root CA cert and private key under {args.root_directory}'
    )
    Network.create(args.network, root_dir, args.password)


if __name__ == '__main__':
    main(sys.argv)
