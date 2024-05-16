#!/usr/bin/env python3

'''
Manage the lists of assets in the cache of the byotube server.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import sys
import os
import logging
import argparse

from datetime import UTC
from datetime import datetime

import anyio

from byoda.datacache.asset_cache import AssetCache

from byoda.util.logger import Logger

_LOGGER: Logger | None = None


async def main(argv: list) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument('--clean', '-c', action='store_true', default=True)
    parser.add_argument(
        '--redis-url', '-r', type=str, default=os.environ.get(
            'REDIS_URL', 'redis://localhost:6379'
        )
    )

    args: argparse.Namespace = parser.parse_args(argv[1:])

    args.debug = True
    global _LOGGER
    if args.debug:
        _LOGGER = Logger.getLogger(
            argv[0], debug=True, json_out=False, loglevel=logging.DEBUG
        )
    else:
        _LOGGER = Logger.getLogger(
            argv[0], json_out=False, loglevel=logging.WARNING
        )

    cache: AssetCache = await AssetCache.setup(args.redis_url)
    # await check_for_dupes(cache, AssetCache.ALL_ASSETS_LIST)
    await check_expirations(cache, AssetCache.ALL_ASSETS_LIST)
    await cache.close()


async def check_for_dupes(cache: AssetCache, list_name: str) -> None:
    list_key: str = cache.get_list_key(list_name)
    keys: list[str] = await cache.client.lrange(list_key, 0, -1)
    keys_set = set(keys)

    if len(keys) != len(keys_set):
        dupes: int = len(keys) - len(keys_set)
        _LOGGER.warning(
            f'Found {dupes} duplicates out of {len(keys)} keys'
        )
        keys_seen = set()
        total: int = 0
        for key in keys:
            if key not in keys_seen:
                keys_seen.add(key)
            else:
                count: int = await cache.client.lrem(list_key, 1, key)
                total += count
                _LOGGER.warning(
                    f'Found duplicate {key}: {count} removed. '
                    f'total removed {total}'
                )


async def check_expirations(cache: AssetCache, list_name: str) -> None:
    list_key: str = cache.get_list_key(list_name)
    keys: list[str] = await cache.client.lrange(list_key, 0, -1)

    keys_not_found: int = 0
    keys_found: int = 0
    for key in keys:
        expiration: int = await cache.get_expiration(key)
        if expiration == -2:
            keys_not_found += 1
            _LOGGER.debug(
                f'Key not found: {key}. Total not found {keys_not_found}'
            )
            await cache.client.lrem(list_key, 1, key)
            continue
        elif expiration == -1:
            _LOGGER.debug(f'Key has no expiration: {key}')
            continue
        else:
            keys_found += 1
            _LOGGER.debug(
                f'Found not-expired key: {key}. Total found: {keys_found}'
            )
    _LOGGER.info(
        f'Checked {len(keys)} assets for expiration, '
        f'{keys_not_found} not found'
    )


if __name__ == '__main__':
    anyio.run(main, sys.argv)
