#!/usr/bin/env python3

import sys
import time
from uuid import UUID

import daemon

import asyncio

from schedule import every, repeat, run_pending

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.datatypes import CloudType

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from byoda.data_import.twitter import Twitter

from byoda import config

from podserver.util import get_environment_vars

LOG_FILE = '/var/www/wwwroot/logs/podworker.log'

_LOGGER = None

ADDRESSBOOK_ID = 4294929430


async def main(argv):
    data = get_environment_vars()

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], json_out=False, debug=True,
        loglevel='DEBUG', logfile=LOG_FILE
    )
    _LOGGER.debug(f'Starting podworker {data["bootstrap"]}')

    config.server = PodServer()
    server = config.server

    await server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType(data['cloud']),
        bucket_prefix=data['bucket_prefix'],
        root_dir=data['root_dir']
    )

    await server.data_store(DataStoreType.SQLITE)

    network = Network(data, data)
    await network.load_network_secrets()

    server.network = network
    server.paths = network.paths

    account = Account(data['account_id'], network)
    await account.paths.create_account_directory()
    await account.load_memberships()

    server.account = account

    if data['bootstrap']:
        await run_bootstrap_tasks(data['account_id'], server)


async def run_bootstrap_tasks(account_id: UUID, server: PodServer):
    '''
    When we are bootstrapping, we create any data that is missing from
    the data store.
    '''

    account: Account = server.account

    _LOGGER.debug('Running bootstrap tasks')
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
        await account.create_account_secret()
        _LOGGER.info('Created account secret during bootstrap')

    try:
        await account.data_secret.load(
            password=account.private_key_password
        )
        _LOGGER.debug('Read account data secret')
    except FileNotFoundError:
        await account.create_data_secret()
        _LOGGER.info('Created account secret during bootstrap')

    _LOGGER.debug('Podworker bootstrap complete')


async def run_startup_tasks(server: PodServer):
    _LOGGER.debug('Running podworker startup tasks')

    account: Account = server.account
    server.twitter_client = None

    if (ADDRESSBOOK_ID in account.memberships
            and Twitter.twitter_integration_enabled()):
        _LOGGER.info('Enabling Twitter integration')
        server.twitter_client = Twitter.client()
        user = server.twitter_client.get_user()
        userdata = server.twitter_client.extract_user_data(user)

        all_tweets, referencing_tweets, media = \
            server.twitter_client.get_tweets(
                with_related=True
            )


def run_daemon():
    global _LOGGER
    data = get_environment_vars()

    with daemon.DaemonContext():
        _LOGGER = Logger.getLogger(
            sys.argv[0], json_out=False, debug=data['debug'],
            loglevel=data.get('loglevel', 'DEBUG'),
            logfile=LOG_FILE
        )

        run_startup_tasks(config.server)

        while True:
            _LOGGER.debug('Daemonized podworker')
            run_pending()
            time.sleep(3)


@repeat(every(5).seconds)
def log_ping_message():
    _LOGGER.debug('Log worker ping message')


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
    run_daemon()
