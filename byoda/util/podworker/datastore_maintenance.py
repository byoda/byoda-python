'''
Various utility classes, variables and functions

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from byoda.servers.pod_server import PodServer

_LOGGER = logging.getLogger(__name__)


async def backup_datastore(server: PodServer):
    '''
    Backs up the account DB and membership DBs to the cloud
    '''

    _LOGGER.info('Backing up datastore')

    await server.data_store.backend.backup_datastore(server)


async def database_maintenance(server: PodServer):
    '''
    This is the place for database maintenance tasks,
    ie. for Sqlite3 it performs WAL compaction
    '''

    await server.data_store.backend.maintain(server)
