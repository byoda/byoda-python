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

from byoda.datastore import MemberDb

from byoda.util.logger import Logger


def main(args):
    config_file = os.environ.get('CONFIG_FILE', 'config.yml')
    with open(config_file) as file_desc:
        app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    global _LOGGER
    _LOGGER = Logger.getLogger(
        sys.argv[0], json_out=True,
        debug=app_config['application']['debug'],
        loglevel=app_config['application'].get('loglevel'),
        logfile=app_config['application']['logfile']
    )
    _LOGGER.debug('Starting podworker')

    memberdb = MemberDb(app_config['svcserver']['cache'])

    while True:
        member = get_member(memberdb)
        data = memberdb.get_data(UUID(member['member_id'])
                                 
        kvcache
        waittime = next_member_wait(data)
        time.sleep(waittime)



if __name__ == '__main__':
    main(sys.argv)
