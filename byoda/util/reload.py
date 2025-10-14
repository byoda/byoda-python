'''
Utility to reload the gunicorn server to pick up a new membership or
the new version of the service contract for a service.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import os
import signal

from logging import Logger
from logging import getLogger
_LOGGER: Logger = getLogger(__name__)

# podserver/files/startup.sh specifies this location for the pid file to
# gunicorn
PODSERVER_PIDFILE = '/var/run/podserver.pid'


def reload_gunicorn() -> None:
    '''
    Reloads the gunicorn server
    '''

    if not os.path.exists(PODSERVER_PIDFILE):
        _LOGGER.debug(
            f'Not reloading as pid file {PODSERVER_PIDFILE} does not exist'
        )
        return

    with open(PODSERVER_PIDFILE) as file_desc:
        pid = int(file_desc.read())

    _LOGGER.info(f'Reloading gunicorn master server with pid {pid}')
    os.kill(pid, signal.SIGHUP)
    _LOGGER.info(f'Gunicorn server process {pid} reloaded')
