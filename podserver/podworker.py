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
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import sys
import asyncio

from aioschedule import every, run_pending

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.datatypes import CloudType

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from byoda import config

from byoda.data_import.twitter import Twitter

from podserver.util import get_environment_vars

from byoda.util.podworker.datastore_maintenance import \
    backup_datastore, database_maintenance

from byoda.util.podworker.twitter import fetch_tweets
from byoda.util.podworker.twitter import twitter_update_task

_LOGGER = None

LOGFILE = '/var/www/wwwroot/logs/worker.log'
ADDRESSBOOK_ID = 4294929430


async def main(argv):
    # Remaining environment variables used:
    data = get_environment_vars()

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], json_out=False, debug=data.get('DEBUG', False),
        loglevel=data.get('loglevel', 'INFO'), logfile=LOGFILE
    )
    _LOGGER.debug(
        f'Starting podworker {data["bootstrap"]}: '
        f'daemonize: {data["daemonize"]}'
    )

    try:
        config.server = PodServer(
            cloud_type=CloudType(data['cloud']),
            bootstrapping=bool(data.get('bootstrap'))
        )
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

    await run_daemon_tasks(server)


async def run_daemon_tasks(server: PodServer):
    '''
    Run the tasks defined for the podworker
    '''

    # This is a separate function to work-around an issue with running
    # aioschedule in a daemon context
    _LOGGER.debug('Scheduling ping message task')
    every(60).seconds.do(log_ping_message)

    _LOGGER.debug('Scheduling twitter update task')
    every(180).seconds.do(twitter_update_task, server)

    if server.cloud != CloudType.LOCAL:
        _LOGGER.debug('Scheduling backups of the datastore')
        every(1).minutes.do(backup_datastore, server)

    _LOGGER.debug('Scheduling Database maintenance tasks')
    every(10).minutes.do(database_maintenance, server)

    await run_startup_tasks(server)

    while True:
        try:
            await run_pending()
            await asyncio.sleep(15)
        except Exception:
            _LOGGER.exception('Exception during run_pending')


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


async def log_ping_message():
    _LOGGER.debug('Log worker ping message')


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
