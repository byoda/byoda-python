'''
Twitter functions for podworker

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

import requests

from schedule import every, repeat

from byoda.servers.pod_server import PodServer

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member

from byoda.datatypes import GRAPHQL_API_URL_PREFIX

from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.util.api_client.graphql_client import GraphQlClient

from byoda.data_import.twitter import Twitter

from tests.lib.addressbook_queries import QUERY_TWEETS
from tests.lib.addressbook_queries import APPEND_TWEETS
from tests.lib.addressbook_queries import APPEND_TWITTER_MEDIAS

from byoda import config

_LOGGER = logging.getLogger(__name__)

NEWEST_TWEET_FILE = 'newest_tweet.txt'


@repeat(every(180).seconds)
def twitter_update_task():

    server: PodServer = config.server

    try:
        if server.twitter_client:
            _LOGGER.debug('Update Twitter data')
            fetch_tweets(server.twitter_client)
        else:
            _LOGGER.debug('Skipping Twitter update as it is not enabled')

    except Exception:
        _LOGGER.exception('Exception during twitter update')
        raise


def find_newest_tweet(account: Account, member: Member, graphql_url: str
                      ) -> str:
    '''
    This function first looks for a local file under /byoda to see if
    the ID of the newest tweet is stored there. If it is, it returns
    that, otherwise it gets all tweets from the pod to see what the
    newest is

    :returns: string with the integer value of the newest Tweet in the pod
    '''

    _LOGGER.debug('Figuring out newest tweet in the pod')

    local_path: str = account.document_store.backend.local_path

    newest_tweet_file = local_path + NEWEST_TWEET_FILE

    try:
        with open(newest_tweet_file, 'r') as file_desc:
            newest_tweet = file_desc.read().strip()
        _LOGGER.debug(
            f'Read newest tweet_id {newest_tweet} from {newest_tweet_file}'
        )
        return newest_tweet
    except OSError:
        newest_tweet = None

    _LOGGER.debug(f'Newest tweet not read from {newest_tweet_file}')
    resp = GraphQlClient.call_sync(
        graphql_url, QUERY_TWEETS, secret=member.tls_secret
    )
    data = resp.json()
    edges = data['data']['tweets_connection']['edges']
    if len(edges):
        _LOGGER.debug(
            f'Discovering newest tweet ID from {len(edges)} tweets from '
            'the pod'
        )
        tweet_ids = set([edge['tweet']['asset_id'] for edge in edges])
        sorted_tweet_ids = sorted(tweet_ids, reverse=True)
        newest_tweet = sorted_tweet_ids[0]
        _LOGGER.debug(f'Newest tweet ID in the pod is {newest_tweet}')
    else:
        _LOGGER.debug('No tweets found in the pod')

    return newest_tweet


def persist_newest_tweet(newest_tweet_file, newest_tweet) -> None:
    '''
    Persists the asset ID of the newest tweet in the pod to local storage
    '''

    try:
        with open(newest_tweet_file, 'w') as file_desc:
            file_desc.write(newest_tweet)
        _LOGGER.debug(
            f'Write newest tweet_id {newest_tweet} '
            f'to {newest_tweet_file}'
        )
    except OSError:
        pass


def fetch_tweets(twitter_client: Twitter, service_id: int):
    _LOGGER.debug('Fetching tweets')

    account: Account = config.server.account
    member: Member = config.server.account.memberships.get(service_id)

    graphql_url = f'https://{member.tls_secret.common_name}'
    graphql_url += GRAPHQL_API_URL_PREFIX.format(service_id=member.service_id)

    newest_tweet = find_newest_tweet(account, member, graphql_url)

    all_tweets, referencing_tweets, media = \
        twitter_client.get_tweets(since_id=newest_tweet, with_related=True)

    for tweet in all_tweets + referencing_tweets:
        _LOGGER.debug(f'Processing tweet {tweet["asset_id"]}')
        try:
            resp: requests.Response = GraphQlClient.call_sync(
                graphql_url, APPEND_TWEETS, vars=tweet,
                secret=member.tls_secret
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

        _LOGGER.debug(f'Successfully appended tweet {tweet["asset_id"]}')

        if tweet.get('mentions') or tweet.get('hashtags'):
            resp = RestApiClient.call_sync(
                account.paths.SERVICEASSETSEARCH_API,
                HttpMethod.POST, secret=member.tls_secret,
                service_id=member.service_id, data={
                    'mentions': tweet.get('mentions'),
                    'hashtags': tweet.get('hashtags'),
                    'asset_id': tweet['asset_id']
                }
            )
            _LOGGER.debug(
                'Asset search POST API response: %s', resp.status_code
            )
        else:
            _LOGGER.debug(
                f'Asset {tweet["asset_id"]} has no mentions or hashtags'
            )

    # Now we have persisted tweets in the pod, we can store
    # the ID of the newest tweet
    if len(all_tweets):
        newest_tweet = all_tweets[0]['asset_id']
        persist_newest_tweet(newest_tweet, newest_tweet)
    else:
        _LOGGER.debug('There were no newer tweets available from Twitter')

    for asset in media:
        _LOGGER.debug(f'Processing Twitter media ID {asset["media_key"]}')
        try:
            resp: requests.Response = GraphQlClient.call_sync(
                graphql_url, APPEND_TWITTER_MEDIAS, vars=asset,
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
