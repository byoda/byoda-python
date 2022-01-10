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

from byoda.datastore.memberdb import MEMBERS_LIST
from byoda.servers.service_server import ServiceServer

from byoda import config

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

        server.member_db.driver.push(MEMBERS_LIST, member_id)
        _LOGGER.debug(f'Processing member_id {member_id}')
        data = server.member_db.get_data(member_id)

        # kvcache
        waittime = next_member_wait(data)
        time.sleep(waittime)


def next_member_wait(data: object) -> int:
    return 10


if __name__ == '__main__':
    main(sys.argv)
