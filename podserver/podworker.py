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

import sys
import time

import daemon

import asyncio

from aioschedule import every, run_pending

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.datatypes import CloudType

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.servers.pod_server import PodServer

from byoda.util.logger import LOGFILE, Logger

from byoda import config

from byoda.data_import.twitter import Twitter

from podserver.util import get_environment_vars

from byoda.util.podworker.backup_datastore import \
    backup_datastore  # noqa: F401

from byoda.util.podworker.twitter import fetch_tweets
from byoda.util.podworker.twitter import twitter_update_task

_LOGGER = None

LOG_FILE = '/var/www/wwwroot/logs/podworker.log'
ADDRESSBOOK_ID = 4294929430


async def main(argv):
    # Remaining environment variables used:
    data = get_environment_vars()

    if data['daemonize']:
        logfile = LOGFILE
    else:
        logfile = None

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], json_out=False, debug=True,
        loglevel='DEBUG', logfile=logfile
    )
    _LOGGER.debug(
        f'Starting podworker {data["bootstrap"]}: '
        f'daemonize: {data["daemonize"]}'
    )

    try:
        config.server = PodServer(cloud_type=CloudType(data['cloud']))
        server = config.server

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            server.cloud,
            bucket_prefix=data['bucket_prefix'],
            root_dir=data['root_dir']
        )
        network = Network(data, data)
        await network.load_network_secrets()

        server.network = network
        server.paths = network.paths

        await server.set_data_store(DataStoreType.SQLITE)

        account = Account(data['account_id'], network)
        await account.paths.create_account_directory()

        server.account = account
    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

    if data.get('bootstrap'):
        _LOGGER.info('Running bootstrap tasks')
        await run_bootstrap_tasks(server)

    await run_daemon(server)


async def run_bootstrap_tasks(server: PodServer):
    '''
    When we are bootstrapping, we create any data that is missing from
    the data store.
    '''

    account: Account = server.account
    account_id = account.account_id

    _LOGGER.debug('Starting bootstrap tasks')
    try:
        await account.tls_secret.load(
            password=account.private_key_password
        )
        common_name = account.tls_secret.common_name
        if not common_name.startswith(str(account.account_id)):
            error_msg = (
                f'Common name of existing account secret {common_name} '
                f'does not match ACCOUNT_ID environment variable {account_id}'
            )
            _LOGGER.exception(error_msg)
            raise ValueError(error_msg)
        _LOGGER.debug('Read account TLS secret')
    except FileNotFoundError:
        try:
            await account.create_account_secret()
            _LOGGER.info('Created account secret during bootstrap')
        except Exception:
            _LOGGER.exception('Exception during startup')
            raise
    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

    try:
        await account.data_secret.load(
            password=account.private_key_password
        )
        _LOGGER.debug('Read account data secret')
    except FileNotFoundError:
        try:
            await account.create_data_secret()
            _LOGGER.info('Created account data secret during bootstrap')
        except Exception:
            raise
    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

    _LOGGER.info('Podworker completed bootstrap')


async def run_startup_tasks(server: PodServer):
    _LOGGER.debug('Running podworker startup tasks')

    account: Account = server.account
    server.twitter_client = None

    try:
        if (ADDRESSBOOK_ID in account.memberships
                and Twitter.twitter_integration_enabled()):
            _LOGGER.info('Enabling Twitter integration')
            server.twitter_client = Twitter.client()
            user = server.twitter_client.get_user()
            server.twitter_client.extract_user_data(user)

            fetch_tweets(server.twitter_client, ADDRESSBOOK_ID)
    except Exception:
        _LOGGER.exception('Exception during startup')
        raise


async def run_daemon(server: PodServer):
    global _LOGGER
    data = get_environment_vars()

    if data['daemonize']:
        _LOGGER.info(f'Daermonizing podworker: {data["daemonize"]}')
        with daemon.DaemonContext():
            _LOGGER = Logger.getLogger(
                sys.argv[0], json_out=False, debug=data['debug'],
                loglevel=data.get('loglevel', 'DEBUG'),
                logfile=LOG_FILE
            )

            # Need to execute run_pending() in a separate async
            # function to work-around an issue with running
            # aioschedule in a daemon context
            asyncio.run(run_daemon_tasks(server, daemonized=True))

    else:
        _LOGGER.debug(f'Not daemonizing podworker: {data["daemonize"]}')
        await run_daemon_tasks(server, daemonized=False)


async def run_daemon_tasks(server: PodServer, daemonized: bool):
    '''
    Run the tasks defined for the podworker
    '''

    # This is a separate function to work-around an issue with running
    # aioschedule in a daemon context
    _LOGGER.debug('Schedling ping message task')
    every(60).seconds.do(log_ping_message)

    _LOGGER.debug('Scheduling twitter update task')
    every(180).seconds.do(twitter_update_task, server)

    if server.cloud != CloudType.LOCAL:
        _LOGGER.debug('Scheduling backups of the datastore')
        every(1).minute.do(backup_datastore, server)

    await run_startup_tasks(server)

    while True:
        try:
            if daemonized:
                asyncio.run(run_pending())
                asyncio.sleep(60)
            else:
                await run_pending()
                time.sleep(3)
        except Exception:
            _LOGGER.exception('Exception during run_pending')


async def log_ping_message():
    _LOGGER.debug('Log worker ping message')


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
