'''
Utility to reload the gunicorn server to pick up a new membership or
the new version of the service contract for a service.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import signal
import logging

_LOGGER = logging.getLogger(__name__)


def reload_gunicorn() -> None:
    '''
    Reloads the gunicorn server
    '''

    pid = os.getpid()
    _LOGGER.info(f'Reloading gunicorn server with pid {pid}')
    _LOGGER.info(f'Gunicorn server process {pid} reloaded')
