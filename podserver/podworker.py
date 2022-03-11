#!/usr/bin/env python3

'''
Manages recurring activities such as checking for new service contracts and
data secrets

Suported environment variables:
CLOUD: 'AWS', 'AZURE', 'GCP', 'LOCAL'
BUCKET_PREFIX
NETWORK
ACCOUNT_ID
ACCOUNT_SECRET
PRIVATE_KEY_SECRET: secret to protect the private key
LOGLEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL
ROOT_DIR: where files need to be cached (if object storage is used) or stored

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
from typing import Dict

import daemon

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.service import BYODA_PRIVATE_SERVICE

from byoda.datatypes import CloudType

from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.pod_server import PodServer

from byoda import config
from byoda.util.logger import Logger

from podserver.util import get_environment_vars


_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/podworker.log'


def main(args):
    # Remaining environment variables used:
    data = get_environment_vars()

    global _LOGGER
    _LOGGER = Logger.getLogger(
        sys.argv[0], json_out=False, debug=True,
        loglevel='DEBUG'
    )
    _LOGGER.debug(f'Starting podworker {data["bootstrap"]}')

    if data['bootstrap']:
        run_bootstrap_tasks(data)

    if data['daemonize']:
        with daemon.DaemonContext():
            _LOGGER = Logger.getLogger(
                sys.argv[0], json_out=False, debug=data['debug'],
                loglevel=os.environ.get('loglevel', 'ERROR'),
                logfile=LOG_FILE
            )
            _LOGGER.debug('Daemonizing podworker')

            schedule_periodic_tasks()

            run_tasks()


def run_bootstrap_tasks(data: Dict):
    '''
    When we are bootstrapping, we create any data that is missing from
    the data store.
    '''

    config.server = PodServer()
    server = config.server
    server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType(data['cloud']),
        bucket_prefix=data['bucket_prefix'],
        root_dir=data['root_dir']
    )

    network = Network(data, data)

    server.network = network
    server.paths = network.paths

    account = Account(data['account_id'], network)
    server.account = account

    _LOGGER.debug('Running bootstrap tasks')
    try:
        account.tls_secret.load(
            password=account.private_key_password
        )
        common_name = account.tls_secret.common_name
        if not common_name.startswith(str(account.account_id)):
            error_msg = (
                f'Common name of existing account secret {common_name} '
                'does not match ACCOUNT_ID environment variable '
                f'{data["account_id"]}'
            )
            _LOGGER.exception(error_msg)
            raise ValueError(error_msg)
        _LOGGER.debug('Read account TLS secret')
    except FileNotFoundError:
        account.create_account_secret()
        _LOGGER.info('Created account secret during bootstrap')

    try:
        account.data_secret.load(
            password=account.private_key_password
        )
        _LOGGER.debug('Read account data secret')
    except FileNotFoundError:
        account.create_data_secret()
        _LOGGER.info('Created account secret during bootstrap')

    if BYODA_PRIVATE_SERVICE not in account.memberships:
        account.join(BYODA_PRIVATE_SERVICE, 1)
        _LOGGER.info('Joined the BYODA private service')

    _LOGGER.debug('Podworker exiting normally')


def schedule_periodic_tasks():
    pass


def run_tasks():
    pass


if __name__ == '__main__':
    main(sys.argv)
