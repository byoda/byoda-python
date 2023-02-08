'''
Various utility classes, variables and functions

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from schedule import every, repeat

from byoda.servers.pod_server import PodServer

from util import config

_LOGGER = logging.getLogger(__name__)


@repeat(every(180).seconds)
async def backup_datastore():
    '''
    Backs up the account DB and membership DBs to the cloud
    '''

    _LOGGER.info('Backing up datastore')
    server: PodServer = config.server

    await server.backend.backup_datastore(server)
