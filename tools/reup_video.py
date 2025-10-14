#!/usr/bin/env python3

'''
Pulls the last video from a list in the asset DB and puts it up front
'''

import sys

import logging
import argparse

from logging import Logger
from logging import getLogger

from anyio import run

from byoda.datatypes import CacheType

from byoda.datacache.kv_redis import KVRedis
from byoda.datacache.asset_cache import AssetCache

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

_LOGGER: Logger = getLogger('')


async def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', default=False, action='store_true')
    parser.add_argument(
        '--network', '-n', type=str, default=config.DEFAULT_NETWORK
    )
    parser.add_argument(
        '--service_id', '-s', type=str, default=ADDRESSBOOK_SERVICE_ID
    )
    parser.add_argument(
        '--redis', '-r', type=str, default='redis://localhost:6379'
    )
    parser.add_argument(
        '--list', '-l', type=str, default=AssetCache.DEFAULT_ASSET_LIST
    )

    args: argparse.Namespace = parser.parse_args(argv[1:])

    global _LOGGER
    if args.debug:
        _LOGGER = ByodaLogger.getLogger(
            argv[0], debug=True, verbose=False, json_out=False,
            loglevel=logging.DEBUG
        )
    else:
        _LOGGER = ByodaLogger.getLogger(
            argv[0], debug=False, verbose=False, json_out=False,
            loglevel=logging.WARNING
        )

    redis = await KVRedis.setup(
        args.redis, args.service_id, args.network, 'ServiceServer',
        CacheType.ASSETDB
    )

    list_key: str = f'AssetCache:AssetList:{args.list}'

    exists: bool = await redis.exists_json_list(list_key)
    if exists:
        _LOGGER.info(f'List {args.list} exists')

    data: dict = await redis.rpop_json_list(list_key)
    result: bool = await redis.lpush_json_list(list_key, data=data)
    print(f'Pushed: {result}: {data}')

if __name__ == '__main__':
    run(main, sys.argv)
