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
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema

from byoda.datatypes import CloudType

from byoda.datastore.data_store import DataStore
from byoda.datastore.data_store import DataStoreType
from byoda.datastore.cache_store import CacheStore
from byoda.datastore.cache_store import CacheStoreType

from byoda.datastore.document_store import DocumentStoreType

from byoda.data_import.youtube import YouTube
from byoda.data_import.twitter import Twitter

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from byoda import config

from podserver.util import get_environment_vars

from podworker.datastore_maintenance import (
    backup_datastore,
    database_maintenance,
    refresh_cached_data,
    expire_cached_data,
)

from podworker.twitter import fetch_tweets
from podworker.twitter import twitter_update_task

from podworker.youtube import youtube_update_task


_LOGGER: Logger | None = None

LOGFILE: str = '/var/www/wwwroot/logs/worker.log'
ADDRESSBOOK_ID: int = 4294929430
YOUTUBE_IMPORT_SERVICE_ID: int = ADDRESSBOOK_ID
TWITTER_IMPORT_SERVICE_ID: int = ADDRESSBOOK_ID


async def main(argv):
    youtube_import_service_id: int = YOUTUBE_IMPORT_SERVICE_ID
    twitter_import_service_id: int = TWITTER_IMPORT_SERVICE_ID

    data: dict[str, str] = get_environment_vars()

    debug = data.get('debug', False)
    if debug and str(debug).lower() in ('true', 'debug', '1'):
        config.debug = True
        # Make our files readable by everyone, so we can
        # use tools like call_data_api.py to debug the server
        os.umask(0o0000)
    else:
        os.umask(0x0077)

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], json_out=True, debug=config.debug,
        loglevel=data.get('worker_loglevel', 'WARNING'), logfile=LOGFILE
    )
    _LOGGER.debug(
        f'Starting pod_worker {data["bootstrap"]}: '
        f'daemonize: {data["daemonize"]}'
    )

    try:
        config.server: PodServer = PodServer(
            cloud_type=CloudType(data['cloud']),
            bootstrapping=bool(data.get('bootstrap'))
        )
        server: PodServer = config.server

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE, server.cloud,
            private_bucket=data['private_bucket'],
            restricted_bucket=data['restricted_bucket'],
            public_bucket=data['public_bucket'],
            root_dir=data['root_dir']
        )

        network: Network = Network(data, data)
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

        await server.set_cache_store(CacheStoreType.SQLITE)
    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

    await run_daemon_tasks(
        server, youtube_import_service_id, twitter_import_service_id
    )


async def run_startup_tasks(server: PodServer, data_store: DataStore,
                            youtube_import_service_id: int,
                            twitter_import_service_id: int) -> None:
    _LOGGER.debug('Running pod_worker startup tasks')

    account: Account = server.account
    server.twitter_client = None

    youtube_member: Member = await account.get_membership(
        youtube_import_service_id, with_pubsub=False
    )
    twitter_member: Member = await account.get_membership(
        twitter_import_service_id, with_pubsub=False
    )

    if youtube_member:
        try:
            _LOGGER.debug('Running startup tasks for membership of YouTube')
            schema: Schema = youtube_member.schema
            schema.get_data_classes(with_pubsub=False)
            await data_store.setup_member_db(
                youtube_member.member_id, youtube_import_service_id,
                youtube_member.schema
            )
        except Exception as exc:
            _LOGGER.exception(f'Exception during startup: {exc}')
            raise
    else:
        _LOGGER.debug(
            'Did not find membership for import of YouTube videos'
        )

    if twitter_member:
        try:
            _LOGGER.debug('Found membership for Twitter import')
            if Twitter.twitter_integration_enabled():
                _LOGGER.info('Enabling Twitter integration')
                server.twitter_client = Twitter.client()
                user = server.twitter_client.get_user()
                server.twitter_client.extract_user_data(user)

                fetch_tweets(
                    server.twitter_client, twitter_import_service_id
                )
        except Exception as exc:
            _LOGGER.exception(f'Exception during startup: {exc}')
            raise
    else:
        _LOGGER.debug('Did not find membership of address book')


async def run_daemon_tasks(server: PodServer, youtube_import_service_id: int,
                           twitter_import_service_id: int) -> None:
    '''
    Run the tasks defined for the pod_worker
    '''

    server: PodServer = config.server
    account: Account = server.account
    data_store: DataStore = server.data_store
    cache_store: CacheStore = server.cache_store

    # This is a separate function to work-around an issue with running
    # aioschedule in a daemon context
    _LOGGER.debug('Scheduling task to update in-memory memberships')
    every(1).minutes.do(
        account.update_memberships, data_store, cache_store, False
    )

    _LOGGER.debug('Scheduling Database maintenance tasks')
    every(10).minutes.do(database_maintenance, server)

    _LOGGER.debug('Scheduling cache refresh task')
    every(30).minutes.do(refresh_cached_data, account, server)

    _LOGGER.debug('Scheduling cache expiration task')
    every(1).hour.do(expire_cached_data, server, cache_store)

    if server.cloud != CloudType.LOCAL:
        _LOGGER.debug('Scheduling backups of the datastore')
        interval: int = int(os.environ.get("BACKUP_INTERVAL", 240) or 240)
        every(interval).minutes.do(backup_datastore, server)

    if Twitter.twitter_integration_enabled():
        _LOGGER.debug('Scheduling twitter update task')
        every(180).seconds.do(twitter_update_task, server)

    if YouTube.youtube_integration_enabled():
        interval: int = int(
            os.environ.get('YOUTUBE_IMPORT_INTERVAL', 240) or 240
        )
        _LOGGER.debug(
            f'Scheduling youtube update task to run every {interval} minutes'
        )
        every(int(interval)).minutes.do(
            youtube_update_task, server, youtube_import_service_id
        )

    await run_startup_tasks(
        server, data_store, youtube_import_service_id,
        twitter_import_service_id
    )

    while True:
        try:
            await run_pending()
            await asyncio.sleep(1)
        except Exception:
            _LOGGER.exception('Exception during run_pending')


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
