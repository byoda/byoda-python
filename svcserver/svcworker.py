'''
Worker that performs queries against registered members of
the service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import yaml

import time

from byoda.datastore.memberdb import MemberDb
from byoda.datastore.memberdb import MEMBERS_LIST

from byoda.util.logger import Logger

MAX_WAIT = 15 * 60


def main(args):
    config_file = os.environ.get('CONFIG_FILE', 'config.yml')
    with open(config_file) as file_desc:
        app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    global _LOGGER
    debug = app_config['application']['debug']
    _LOGGER = Logger.getLogger(
        sys.argv[0], json_out=True,
        debug=debug,
        loglevel=app_config['application'].get('loglevel', 'INFO'),
        logfile=app_config['svcserver'].get('logfile')
    )
    _LOGGER.debug('Starting podworker')

    if debug:
        global MAX_WAIT
        MAX_WAIT = 10

    memberdb = MemberDb(app_config['svcserver']['cache'])
    memberdb.

    while True:
        member_id = memberdb.get_next(timeout=MAX_WAIT)
        if not member_id:
            _LOGGER.debug('No member available in list of members')
            continue

        memberdb.driver.push(MEMBERS_LIST, member_id)
        _LOGGER.debug(f'Processing member_id {member_id}')
        data = memberdb.get_data(member_id)

        # kvcache
        waittime = next_member_wait(data)
        time.sleep(waittime)


def next_member_wait(data: object) -> int:
    return 10


if __name__ == '__main__':
    main(sys.argv)
