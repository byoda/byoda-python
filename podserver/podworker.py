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
from uuid import UUID

import daemon
import requests

import asyncio

from schedule import every, repeat, run_pending

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import GRAPHQL_API_URL_PREFIX
from byoda.datatypes import CloudType

from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.pod_server import PodServer

from byoda import config
from byoda.util.logger import Logger

from byoda.exceptions import PodException

from podserver.util import get_environment_vars

from byoda.data_import.twitter import Twitter

from byoda.util.api_client.graphql_client import GraphQlClient

from tests.lib.addressbook_queries import QUERY_TWEETS
from tests.lib.addressbook_queries import APPEND_TWEETS
from tests.lib.addressbook_queries import APPEND_TWITTER_MEDIAS

_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/podworker.log'
ADDRESSBOOK_ID = 4294929430


async def main(argv):
    # Remaining environment variables used:
    data = get_environment_vars()

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], json_out=False, debug=True,
        loglevel='DEBUG', logfile=LOG_FILE
    )
    _LOGGER.debug(f'Starting podworker {data["bootstrap"]}')

    try:
        config.server = PodServer()
        server = config.server
        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            cloud_type=CloudType(data['cloud']),
            bucket_prefix=data['bucket_prefix'],
            root_dir=data['root_dir']
        )

        network = Network(data, data)
        await network.load_network_secrets()

        server.network = network
        server.paths = network.paths

        account = Account(data['account_id'], network)
        await account.paths.create_account_directory()
        await account.load_memberships()

        server.account = account
    except PodException:
        raise

    _LOGGER.info('Load of account and memberships complete')

    if data.get('bootstrap'):
        _LOGGER.info('Running bootstrap tasks')
        await run_bootstrap_tasks(data['account_id'], server)


async def run_bootstrap_tasks(account_id: UUID, server: PodServer):
    '''
    When we are bootstrapping, we create any data that is missing from
    the data store.
    '''

    account: Account = server.account

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
        except PodException:
            raise

    try:
        await account.data_secret.load(
            password=account.private_key_password
        )
        _LOGGER.debug('Read account data secret')
    except FileNotFoundError:
        try:
            await account.create_data_secret()
            _LOGGER.info('Created account secret during bootstrap')
        except PodException:
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
            user = await server.twitter_client.get_user()
            server.twitter_client.extract_user_data(user)

            fetch_tweets(server.twitter_client)
    except PodException:
        raise


@repeat(every(5).seconds)
def log_ping_message():
    _LOGGER.debug('Log worker ping message')


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


@repeat(every(30).seconds)
def twitter_update_task(server: PodServer):

    try:
        _LOGGER.debug('Update Twitter data')
        if server.twitter_client:
            fetch_tweets(server.twitter_client)

    except PodException:
        raise


def fetch_tweets(twitter_client: Twitter):
    _LOGGER.debug('Fetching tweets')
    account: Account = config.server.account
    local_path: str = account.document_store.backend.local_path
    newest_tweet_file = local_path + '/newest_tweet.txt'
    try:
        with open(newest_tweet_file, 'r') as file_desc:
            newest_tweet = file_desc.read().strip()
    except OSError:
        newest_tweet = None

    member: Member = config.server.account.memberships.get(ADDRESSBOOK_ID)
    url = f'https://{member.tls_secret.common_name}'
    url += GRAPHQL_API_URL_PREFIX.format(service_id=member.service_id)

    if not newest_tweet:
        resp = GraphQlClient.call_sync(
            url, QUERY_TWEETS, secret=member.secret
        )
        data = resp.json()
        edges = data['data']['tweets_connection']['edges']
        tweet_ids = set([edge['tweet']['asset_id'] for edge in edges])
        sorted_tweet_ids = sorted(tweet_ids, reverse=True)[0]
        newest_tweet = sorted_tweet_ids[0]

    all_tweets, referencing_tweets, media = \
        twitter_client.get_tweets(since_id=newest_tweet, with_related=True)

    for tweet in all_tweets + referencing_tweets:
        _LOGGER.debug(f'Processing tweet {tweet["asset_id"]}')
        try:
            resp: requests.Response = GraphQlClient.call_sync(
                url, APPEND_TWEETS, vars=tweet, secret=member.tls_secret
            )
        except Exception as exc:
            _LOGGER.info(
                f'Failed to call GraphQL API for tweet {tweet["asset_id"]}: '
                f'{exc}, will try again in the next run of this task'
            )
            return

        if resp.status_code != 200:
            _LOGGER.info(
                f'Failed to call GraphQL API for tweet {tweet["asset_id"]}: '
                f'{resp.status_code}, will try again in the next run of this '
                'task'
            )
            return

        data = resp.json()
        if data.get('errors'):
            _LOGGER.info(
                f'GraphQL API for {tweet["asset_id"]} returned errors: '
                f'{data["errors"]}, will try again in the next run of this '
                'task'
            )
            return

    # Now we have persisted tweets in the pod, we can store
    # the ID of the newest tweet
    newest_tweet = all_tweets[0]['asset_id']
    try:
        with open(newest_tweet_file, 'w') as file_desc:
            newest_tweet = file_desc.write()
    except OSError:
        pass

    for asset in media:
        _LOGGER.debug(f'Processing Twitter media ID {asset["media_key"]}')
        try:
            resp: requests.Response = GraphQlClient.call_sync(
                url, APPEND_TWITTER_MEDIAS, vars=asset,
                secret=member.tls_secret
            )
        except Exception as exc:
            _LOGGER.info(
                f'Failed to call GraphQL API for media {asset["media_key"]}: '
                f'{exc}, will try again in the next run of this task'
            )
            return

        if resp.status_code != 200:
            _LOGGER.info(
                f'Failed to call GraphQL API for media {tweet["media_key"]}: '
                f'{resp.status_code}, will try again in the next run of this '
                'task'
            )
            return

        data = resp.json()
        if data.get('errors'):
            _LOGGER.info(
                f'GraphQL API for media {tweet["media_key"]} returned errors: '
                f'{data["errors"]}, will try again in the next run of this '
                'task'
            )
            return


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
    run_daemon()
