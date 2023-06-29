#!/usr/bin/env python3

'''
Manages recurring activities such as checking for new service contracts and
data secrets

Suported environment variables:
CLOUD: 'AWS', 'AZURE', 'GCP', 'LOCAL'
PRIVATE_BUCKET
RESTRICTED_BUCKET
PUBLIC_BUCKET
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

import os
import sys
import asyncio

from aioschedule import every, run_pending

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.datatypes import CloudType

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.data_import.youtube import YouTube
from byoda.data_import.twitter import Twitter

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from byoda import config

from podserver.util import get_environment_vars

from .podworker.datastore_maintenance import \
    backup_datastore, database_maintenance

from .podworker.twitter import fetch_tweets
from .podworker.twitter import twitter_update_task

from .podworker.youtube import youtube_update_task


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
            DocumentStoreType.OBJECT_STORE, server.cloud,
            private_bucket=data['private_bucket'],
            restricted_bucket=data['restricted_bucket'],
            public_bucket=data['public_bucket'],
            root_dir=data['root_dir']
        )

        network = Network(data, data)
        await network.load_network_secrets()

        server.network = network
        server.paths = network.paths

        account = Account(data['account_id'], network)
        await account.paths.create_account_directory()
        await account.load_secrets()

        server.account = account

        await server.set_data_store(
            DataStoreType.SQLITE, account.data_secret
        )
    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

    await run_daemon_tasks(server)


async def run_startup_tasks(server: PodServer):
    _LOGGER.debug('Running podworker startup tasks')

    account: Account = server.account
    server.twitter_client = None

    try:
        await server.account.load_memberships()
        member = account.memberships.get(ADDRESSBOOK_ID)
        if member:
            if Twitter.twitter_integration_enabled():
                _LOGGER.info('Enabling Twitter integration')
                server.twitter_client = Twitter.client()
                user = server.twitter_client.get_user()
                server.twitter_client.extract_user_data(user)

                fetch_tweets(server.twitter_client, ADDRESSBOOK_ID)
        else:
            _LOGGER.debug('Did not find membership of address book')

    except Exception:
        _LOGGER.exception('Exception during startup')
        raise


async def run_daemon_tasks(server: PodServer):
    '''
    Run the tasks defined for the podworker
    '''

    # This is a separate function to work-around an issue with running
    # aioschedule in a daemon context
    _LOGGER.debug('Scheduling ping message task')
    every(60).seconds.do(log_ping_message)

    if server.cloud != CloudType.LOCAL:
        _LOGGER.debug('Scheduling backups of the datastore')
        interval: int = int(os.environ.get("BACKUP_INTERVAL", 240))
        every(interval).minutes.do(backup_datastore, server)

    _LOGGER.debug('Scheduling Database maintenance tasks')
    every(10).minutes.do(database_maintenance, server)

    if Twitter.twitter_integration_enabled():
        _LOGGER.debug('Scheduling twitter update task')
        every(180).seconds.do(twitter_update_task, server)

    if YouTube.youtube_integration_enabled():
        interval: int = int(os.environ.get('YOUTUBE_IMPORT_INTERVAL', 240))
        _LOGGER.debug(
            f'Scheduling youtube update task to run every {interval} minutes'
        )
        every(int(interval)).minutes.do(youtube_update_task, server)

    await run_startup_tasks(server)

    while True:
        try:
            await run_pending()
            await asyncio.sleep(15)
        except Exception:
            _LOGGER.exception('Exception during run_pending')


async def log_ping_message():
    _LOGGER.debug('Log worker ping message')


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
