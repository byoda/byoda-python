'''
Various utility classes, variables and functions

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from logging import getLogger

from anyio import create_task_group

from byoda.datamodel.account import Account
from byoda.datamodel.schema import Schema
from byoda.datamodel.dataclass import SchemaDataItem


from byoda.datastore.cache_store import CacheStore

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)


async def backup_datastore(server: PodServer) -> None:
    '''
    Backs up the account DB and membership DBs to the cloud
    '''

    _LOGGER.info('Backing up datastore')

    try:
        await server.data_store.backend.backup_datastore(server)
    except Exception:
        _LOGGER.exception('Backup of data store failed')


async def database_maintenance(server: PodServer) -> None:
    '''
    This is the place for database maintenance tasks,
    ie. for Sqlite3 it performs WAL compaction
    '''

    try:
        await server.data_store.backend.maintain(server)
    except Exception:
        _LOGGER.exception('Maintenance of data store failed')


async def refresh_cached_data(account: Account, server: PodServer) -> None:
    '''
    Refresh content in the cache that is close to expiring

    :param account: the account of this pod
    :param cache_store: the cache store of this pod
    :returns: (none)
    '''
    _LOGGER.debug('Starting expiration of cached data')

    async with create_task_group() as tg:
        for member in account.memberships.values():
            schema: Schema = member.schema
            data_class: SchemaDataItem
            for data_class in schema.data_classes.values():
                if not data_class.cache_only:
                    continue

                cache_store: CacheStore = server.cache_store
                tg.start_soon(
                    cache_store.refresh_table, server, member, data_class
                )


async def expire_cached_data(server: PodServer, cache_store: CacheStore
                             ) -> None:
    '''
    For each membership, expire data for cache-only data classes

    :param account: the account of this pod
    :param cache_store: the cache store of this pod
    :returns: (none)
    '''

    _LOGGER.debug('Starting expiration of cached data')

    account: Account = server.account
    async with create_task_group() as tg:
        for member in account.memberships.values():
            schema: Schema = member.schema
            data_class: SchemaDataItem
            for data_class in schema.data_classes.values():
                if not data_class.cache_only:
                    continue

                tg.start_soon(
                    cache_store.expire_table, server, member,
                    data_class
                )
