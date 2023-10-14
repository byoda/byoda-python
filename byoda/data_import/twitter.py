'''
Import data from Twitter

NOTE: We only support Twitter import using an API key,
which Twitter has started requiring a $100/m developer
account for. We do not yet support scraping Twitter

Requires enabling Twitter Development API. Sign up at
https://developer.twitter.com/en

Takes as input environment variables
TWITTER_USERNAME
TWITTER_API_KEY
TWITTER_KEY_SECRET

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from logging import getLogger
from byoda.util.logger import Logger
from datetime import datetime
from datetime import timezone

import requests
from requests.auth import HTTPBasicAuth

from dateutil.parser import parse as dateutil_parse

import tweepy
from tweepy.tweet import Tweet
from tweepy.media import Media


_LOGGER: Logger = getLogger(__name__)

ENVIRON_TWITTER_API_KEY: str = 'TWITTER_API_KEY'
ENVIRON_TWITTER_KEY_SECRET: str = 'TWITTER_KEY_SECRET'
ENVIRON_TWITTER_USERNAME: str = 'TWITTER_USERNAME'

USER_FIELDS: list[str] = [
    'created_at', 'description', 'entities', 'id', 'location',
    'name', 'pinned_tweet_id', 'profile_image_url', 'protected',
    'public_metrics', 'url', 'username', 'verified', 'withheld',
]

USER_FIELDS_MAPPINGS: list[str] = {
    'twitter_id': 'id',
    'created_timestamp': None,      # Field requires conversion to a datetime
    'url': None,
    'display_url': None,
    'name': 'name',
    'pinned_tweet_id': 'pinned_tweet_id',
    'profile_image_url': 'profile_image_url',
    'followers_count': 'public_metrics/followers_count',
    'following_count': 'public_metrics/following_count',
    'tweet_count': 'public_metrics/tweet_count',
    'listed_count': 'public_metrics/listed_count',
    'username': 'handle',
    'verified': 'verified',
    'protected': 'protected',
    'withheld': None,
}


MEDIA_FIELDS: list[str] = [
    'media_key', 'type', 'url', 'duration_ms', 'height', 'width',
    'preview_image_url', 'public_metrics', 'alt_text', 'variants',
]

MEDIA_FIELDS_MAPPINGS: list[str] = {
    'media_key': 'media_key',
    'type': 'media_type',
    'height': 'height',
    'width': 'width',
    'view_count:': 'public_metrics/view_count',
    'url': 'url',
}

# 'organic_metrics' and 'promoted_metrics' are not included in the
# results because authorization is denied
TWEET_FIELDS: list[str] = [
    'id', 'text', 'created_at', 'attachments', 'author_id',
    'context_annotations', 'conversation_id', 'entities', 'geo',
    'in_reply_to_user_id', 'lang', 'possibly_sensitive', 'public_metrics',
    'referenced_tweets', 'reply_settings', 'source', 'withheld',
]

TWEET_FIELDS_MAPPINS: list[str] = {
    'created_timestamp': None,      # Field requires conversion to a datetime
    'asset_id': 'id',
    'locale': 'lang',
    'creator': 'author_id',
    'contents': 'text',
    'response_to': 'in_reply_to_user_id',
    'conversation_id': 'conversation_id',
    'geo': 'geo',
    'media_keys': 'attachments/media_keys',
    "retweet_count": "public_metrics/retweet_count",
    "reply_count": "public_metrics/reply_count",
    "like_count": "public_metrics/like_count",
    "quote_count": "public_metrics/quote_count",
}


class Twitter:
    def __init__(self, api_key: str = None, key_secret: str = None):
        '''
        Constructor, do not call this directly, use the Twitter.async_client()
        factory
        '''

        self.api_key = api_key
        if not self.api_key:
            self.api_key: str = os.environ.get('TWITTER_API_KEY')

        self.key_secret = key_secret
        if not self.key_secret:
            self.key_secret: str = os.environ.get('TWITTER_KEY_SECRET')

        self.username: str = os.environ.get(ENVIRON_TWITTER_USERNAME)
        self.id: str = None

        self.client = None
        self.bearer_token: str = None

    @staticmethod
    def twitter_integration_enabled() -> bool:
        if (os.environ.get(ENVIRON_TWITTER_API_KEY)
                and os.environ.get(ENVIRON_TWITTER_KEY_SECRET)
                and os.environ.get(ENVIRON_TWITTER_USERNAME)):
            _LOGGER.debug('Enabling Twitter integration')

            return True

        _LOGGER.debug(
            f'Twitter integration disabled: '
            f'TWITTER_USERNAME: {os.environ.get(ENVIRON_TWITTER_USERNAME)} '
        )
        return False

    @staticmethod
    def client(api_key: str = None, key_secret: str = None):
        '''
        Factory for Twitter instance
        '''

        twit = Twitter(api_key=api_key, key_secret=key_secret)

        response = requests.post(
            'https://api.twitter.com/oauth2/token',
            auth=HTTPBasicAuth(twit.api_key, twit.key_secret),
            data={'grant_type': 'client_credentials'}
        )

        if response.status_code != 200:
            raise RuntimeError('Failed to get bearer token')

        data = response.json()
        twit.bearer_token = data['access_token']

        twit.client = tweepy.Client(
            bearer_token=twit.bearer_token, wait_on_rate_limit=True,
        )

        twit.client.user_agent = 'Byoda Twitter Client'

        return twit

    def get_user(self, id: str = None, username: str = None) -> tweepy.User:
        '''
        Get user data from Twitter
        '''

        if not id and not username:
            username = os.environ[ENVIRON_TWITTER_USERNAME]

        response = self.client.get_user(
            id=id, username=username, user_fields=USER_FIELDS
        )

        user = response.data

        self.id = user.id

        return user

    def extract_user_data(self, user: tweepy.User) -> dict:
        '''
        Updates the Byoda data for the user

        returns: dict with keys matching the 'twitter_person' dict in the
        address book service contract
        '''

        data = {}
        for field, twitter_field in USER_FIELDS_MAPPINGS.items():
            if not twitter_field:
                continue

            if '/' not in twitter_field:
                data[field] = user.data.get(twitter_field)
            else:
                keys = twitter_field.split('/')
                if len(keys) == 2 and keys[0] in user.data:
                    data[field] = user.data[keys[0]].get(keys[1])

        data['created_timestamp'] = dateutil_parse(user.data['created_at'])

        entities = user.data.get('entities')
        if entities and entities.get('url'):
            urls = entities['url'].get('urls')
            if urls and len(urls):
                data['display_url'] = urls[0].get('display_url')
                data['url'] = urls[0].get('expanded_url')

        withheld = data.get('withheld')
        if withheld and withheld.get('countries'):
            data['withheld'] = ','.join(withheld['countries'])

        return data

    def get_tweets(self, since_id: str = None, with_related: bool = True
                   ) -> tuple[dict, dict, dict]:
        '''
        Get user's tweets from Twitter
        '''

        if not self.id:
            raise ValueError(
                'get_user() must be called or Twitter.id must be set before'
                'reconcile_tweets()'
            )

        max_tweets = 100
        condition = True
        all_tweets = []
        all_media = []
        all_referencing_tweets = []
        while condition:
            response = self.client.get_users_tweets(
                self.id, tweet_fields=TWEET_FIELDS,
                expansions=[
                    'attachments.media_keys', 'referenced_tweets.id'
                ],
                media_fields=MEDIA_FIELDS,
                since_id=since_id, max_results=max_tweets
            )

            tweets: list[Tweet] = response.data or []
            media: list[Media] = response.includes.get('media', [])
            referencing_tweets = response.includes.get('tweets', [])

            since_id = None
            if len(tweets):
                since_id = tweets[-1].id

            for media_asset in media:
                asset = _translate_media_to_asset(media_asset)
                all_media.append(asset)

            for tweet in tweets:
                asset = _translate_tweet_to_asset(tweet)
                all_tweets.append(asset)

            if with_related:
                for tweet in referencing_tweets:
                    asset = _translate_tweet_to_asset(tweet)
                    if asset:
                        all_referencing_tweets.append(asset)

            condition = len(tweets) >= max_tweets

        return all_tweets, all_referencing_tweets, all_media


def _translate_tweet_to_asset(tweet: Tweet) -> dict:
    '''
    Translates a Tweet instance or a dict included in the 'includes'
    of a Tweepy Response object into an asset dict
    '''

    if isinstance(tweet, Tweet):
        data = tweet.data
    else:
        data = tweet
        if not data.get('creator'):
            # This may be a bug in Tweepy. For referencing tweets,
            # after a first x number of Tweet instances, Tweepy returns
            # dicts with only a value for the the 'conversation_id' key
            return

    asset = {}

    for field, twitter_field in TWEET_FIELDS_MAPPINS.items():
        if not twitter_field:
            continue

        if '/' not in twitter_field:
            asset[field] = data.get(twitter_field)
        else:
            keys = twitter_field.split('/')
            if len(keys) == 2 and keys[0] in data:
                asset[field] = data[keys[0]].get(keys[1])

    asset['created_timestamp'] = dateutil_parse(
        data.get('created_at', '1970-01-01T00:00:00+00:00')
    )
    referenced_tweets = data.get('referenced_tweets')
    asset['referenced_tweets'] = []
    if referenced_tweets and isinstance(referenced_tweets, list):
        for referenced_tweet in referenced_tweets:
            if isinstance(referenced_tweet, str):
                asset['referenced_tweets'].append(referenced_tweet)
            else:
                asset['referenced_tweets'].append(referenced_tweet.get('id'))

    asset['urls'] = []
    asset['mentions'] = []
    asset['hashtags'] = []
    if 'entities' in data:
        entities = data['entities']
        if entities:
            for url in entities.get('urls', []):
                asset['urls'].append(url['expanded_url'])

            for mention in entities.get('mentions', []):
                asset['mentions'].append(mention['username'])

            for hashtag in entities.get('hashtags', []):
                asset['hashtags'].append(hashtag['tag'])

    return asset


def _translate_media_to_asset(media: Media) -> dict:
    asset = {}
    for field, twitter_field in MEDIA_FIELDS_MAPPINGS.items():
        if not twitter_field:
            continue

        if '/' not in twitter_field:
            asset[field] = media.data.get(twitter_field)
        else:
            keys = twitter_field.split('/')
            if len(keys) == 2 and keys[0] in media.data:
                asset[field] = media.data[keys[0]].get(keys[1])

    asset['created_timestamp'] = datetime.now(timezone.utc)

    return asset
