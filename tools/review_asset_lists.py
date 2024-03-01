#!/usr/bin/env python3

'''
Manage the lists of assets in the cache of the svcserver.

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

from byoda.models.data_api_models import EdgeResponse as Edge

from byoda.datacache.asset_cache import AssetCache

from byoda.util.logger import Logger

_LOGGER: Logger | None = None


async def main(argv: list) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument('--clean', '-c', action='store_true', default=True)
    parser.add_argument('--max-pages', '-m', type=int, default=10)
    parser.add_argument('--min-videos', '-i', type=int, default=20)
    parser.add_argument(
        '--template-dir', '-t', type=str, default='svcserver/files'
    )
    parser.add_argument(
        '--pages-directory', '-p', type=str, default='/var/www/wwwroot/pages'
    )
    parser.add_argument(
        '--redis-url', '-r', type=str, default=os.environ.get(
            'REDIS_URL', 'http://localhost:6379'
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
    await check_for_dupes(cache, AssetCache.ALL_ASSETS_LIST)
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
        keys_set = set(keys)
        for key in keys:
            if key not in keys_set:
                keys_set.add(key)
                continue

            count: int = await cache.client.lrem(list_key, 1, key)
            _LOGGER.warning(f'Found duplicate {key}: {count} removed')


async def check_expirations(cache: AssetCache, list_name: str) -> None:
    list_key: str = cache.get_list_key(list_name)
    keys: list[str] = await cache.client.lrange(list_key, 0, -1)

    previous_expiration: float = datetime.now(tz=UTC).timestamp()
    asset: dict[str, any] | None = None
    keys_not_found: int = 0
    for key in keys:
        expiration: int = await cache.get_expiration(key)
        if expiration == -2:
            _LOGGER.debug(f'Key not found: {key}')
            keys_not_found += 1
            await cache.client.lrem(list_key, 1, key)
            continue
        if expiration == -1:
            _LOGGER.debug(f'Key has no expiration: {key}')
            continue

        if previous_expiration < expiration:
            asset: dict[str, any] = await cache.json_get(key)
            _LOGGER.warning(f'Found asset {asset["asset_id"]}')
            await cache.client.lrem(list_key, 0, key)
            await cache.client.delete(key)

    _LOGGER.info(
        f'Checked {len(keys)} assets for expiration, '
        f'{keys_not_found} not found'
    )


if __name__ == '__main__':
    anyio.run(main, sys.argv)
