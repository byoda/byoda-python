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
from datetime import datetime, timedelta

from byoda.servers.service_server import ServiceServer

from byoda import config

from byoda.util.logger import Logger

MAX_WAIT = 15 * 60
MEMBER_PROCESS_INTERVAL = 8 * 60 * 60


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
    _LOGGER.debug(
        'Starting service worker for service ID: '
        f'{app_config["svcserver"]["service_id"]}'
    )

    if debug:
        global MAX_WAIT
        MAX_WAIT = 10

    server = ServiceServer(app_config)
    config.server = server

    if not server.service.paths.service_file_exists(server.service.service_id):
        server.service.download_schema(save=True)
    server.load_schema(verify_contract_signatures=False)

    while True:
        member_id = server.member_db.get_next(timeout=MAX_WAIT)
        if not member_id:
            _LOGGER.debug('No member available in list of members')
            continue

        server.member_db.add_member(member_id)
        _LOGGER.debug(f'Processing member_id {member_id}')
        data = server.member_db.get_meta(member_id)

        waittime = next_member_wait(data['last_seen'])
        server.member_db.add_meta(
            data['member_id'], data['remote_addr'], data['schema_version'],
            data['data_secret'], data['status']
        )

        #
        # Here is where we can do stuff
        #
        
        time.sleep(waittime)


def next_member_wait(last_seen: datetime) -> int:
    '''
    Calculate how long to wait before processing the next member
    in the list. We calculate using the last_seen time of the
    current member, knowing that it is always less than the wait
    time of the next member. So we're okay with processing the
    next member to early.
    '''

    now = datetime.utcnow()

    waittime = last_seen + timedelta(seconds=MEMBER_PROCESS_INTERVAL) - now

    if waittime.seconds < 0:
        waittime.seconds = 0

    wait = min(waittime.seconds, MAX_WAIT)

    return wait


if __name__ == '__main__':
    main(sys.argv)
