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
import anyio

from logging import Logger

from byoda.datacache.asset_cache import AssetCache

from byoda.util.logger import Logger as ByodaLogger

_LOGGER: Logger | None = None

MAX_LIST_LENGTH: int = 2000


async def main(argv: list) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument('--clean', '-c', action='store_true', default=False)
    parser.add_argument(
        '--skip-list', '-s', type=str, default='/tmp/skip.list'
    )
    parser.add_argument(
        '--redis-url', '-r', type=str, default=os.environ.get(
            'REDIS_URL', 'redis://localhost:6379'
        )
    )
    args: argparse.Namespace = parser.parse_args(argv[1:])

    global _LOGGER
    if args.debug:
        _LOGGER = ByodaLogger.getLogger(
            argv[0], debug=True, json_out=True, loglevel=logging.DEBUG
        )
    else:
        _LOGGER = ByodaLogger.getLogger(
            argv[0], json_out=False, loglevel=logging.WARNING
        )

    cache: AssetCache = await AssetCache.setup(args.redis_url)
    all_lists: list[str] = await cache.client.smembers('lists:list_of_lists')

    skip_list: set[str] = set()
    if os.path.exists(args.skip_list):
        with open(args.skip_list, 'r') as file_desc:
            skip_list = set(file_desc.read().splitlines())
    skip_list.add('list_of_lists')
    skip_list.add('all_assets')
    skip_list.add(AssetCache.ALL_ASSETS_LIST)

    for list_name in all_lists:
        if cache.is_channel_list(list_name):
            continue
        if list_name[0].islower():
            continue

        print(f'Old-format name for: {list_name}')
        list_key: str = cache.get_list_key(list_name)
        await cache.client.delete(list_key)
        await cache.client.srem('lists:list_of_lists', list_name)

        if list_name in skip_list:
            continue

        await check_for_dupes(cache, list_name)
        with open(args.skip_list, 'a') as file_desc:
            file_desc.write(f'{list_name}\n')

        if args.clean:
            await check_expirations(cache, list_name)
            await check_expirations(cache, AssetCache.ALL_ASSETS_LIST)

    await check_for_dupes(cache, AssetCache.ALL_ASSETS_LIST)
    await cache.close()


async def check_for_dupes(cache: AssetCache, list_name: str) -> None:
    list_key: str = cache.get_list_key(list_name)
    keys: list[str] = await cache.client.lrange(list_key, 0, -1)

    log_data: dict[str, any] = {
        'list_name': list_name,
        'found_keys': len(keys),
    }

    keys_set = set(keys)
    if len(keys) == len(keys_set):
        _LOGGER.debug('No duplicate keys found in list', extra=log_data)
    else:
        dupes: int = len(keys) - len(keys_set)
        log_data['dupes'] = dupes
        _LOGGER.warning('Found duplicate keys in list', extra=log_data)
        keys_seen = set()
        new_keys: list[str] = []
        for key in keys:
            if key not in keys_seen:
                keys_seen.add(key)
                new_keys.append(key)

        if len(new_keys) >= len(keys):
            _LOGGER.error(
                'Failed to remove duplicate keys from list', extra=log_data
            )
            return

        await cache.client.delete(list_key)
        if cache.is_channel_list(list_name):
            await cache.client.rpush(list_key, *new_keys[0:MAX_LIST_LENGTH])
        else:
            await cache.client.rpush(list_key, *new_keys)
        _LOGGER.warning(
            'Removed duplicate keys from list', extra=log_data
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
                f'List {list_name} Key not found: {key}. '
                f'Total not found {keys_not_found}'
            )
            await cache.client.lrem(list_key, 1, key)
            await cache.remove_asset(key)
            continue
        elif expiration == -1:
            _LOGGER.debug(f'Key has no expiration: {key}')
            continue
        else:
            keys_found += 1
    _LOGGER.info(
        f'Checked {len(keys)} assets in list {list_name} for expiration, '
        f'{keys_not_found} not found'
    )


if __name__ == '__main__':
    anyio.run(main, sys.argv)
