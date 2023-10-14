'''
Various utility classes, variables and functions

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from logging import getLogger
from byoda.util.logger import Logger

from byoda.servers.pod_server import PodServer

_LOGGER: Logger = getLogger(__name__)


async def backup_datastore(server: PodServer):
    '''
    Backs up the account DB and membership DBs to the cloud
    '''

    _LOGGER.info('Backing up datastore')

    try:
        await server.data_store.backend.backup_datastore(server)
    except Exception:
        _LOGGER.exception('Backup of data store failed')


async def database_maintenance(server: PodServer):
    '''
    This is the place for database maintenance tasks,
    ie. for Sqlite3 it performs WAL compaction
    '''

    try:
        await server.data_store.backend.maintain(server)
    except Exception:
        _LOGGER.exception('Maintenance of data store failed')
