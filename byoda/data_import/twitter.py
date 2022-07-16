'''
Import data from Twitter

Requires enabling Twitter Development API. Sign up at
https://developer.twitter.com/en

Takes as input environment variables
TWITTER_API_KEY
TWITTER_KEY_SECRET

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import logging
from typing import Dict

import aiohttp

from dateutil.parser import parse as dateutil_parse

import tweepy
from tweepy.asynchronous import AsyncClient as TweepyAsyncClient

_LOGGER = logging.getLogger(__name__)

ENVIRON_TWITTER_API_KEY = 'TWITTER_API_KEY'
ENVIRON_TWITTER_KEY_SECRET = 'TWITTER_KEY_SECRET'
ENVIRON_TWITTER_USERNAME = 'TWITTER_USERNAME'

TWITTER_FIELDS = [
    'attachments', 'author_id', 'context_annotations',
    'conversation_id', 'created_at', 'entities', 'geo',
    'in_reply_to_user_id', 'lang', 'non_public_metrics',
    'organic_metrics', 'possibly_sensitive', 'promoted_metrics',
    'public_metrics', 'reply_settings', 'source'
]

USER_FIELDS = [
    'created_at', 'description', 'entities', 'id', 'location',
    'name', 'pinned_tweet_id', 'profile_image_url', 'protected',
    'public_metrics', 'url', 'username', 'verified', 'withheld',
]

FIELDS_MAPPINGS = {
    'twitter_id': 'id',
    'created_at': None,     # This field requires conversion to a datetime
    'url': None,
    'display_url': None,
    'name': 'name',
    'pinned_tweet_id': 'pinned_tweet_id',
    'profile_image_url': 'profile_image_url',
    'followers_count': None,
    'following_count': None,
    'tweet_count': None,
    'listed_count': None,
    'username': 'username',
    'verified': 'verified',
    'withheld': 'withheld',
}


class Twitter:
    def __init__(self, api_key: str = None, key_secret: str = None):
        '''
        Constructor, do not call this directly, use the Twitter.async_client()
        factory
        '''

        self.api_key = api_key
        if not self.api_key:
            self.api_key = os.environ.get('TWITTER_API_KEY')

        self.key_secret = key_secret
        if not self.key_secret:
            self.key_secret = os.environ.get('TWITTER_KEY_SECRET')

        self.client = None
        self.bearer_token = None

    @staticmethod
    def twitter_integration_enabled() -> bool:
        if (os.environ.get('ENVIRON_TWITTER_API_KEY')
                and os.environ.get('ENVIRON_TWITTER_KEY_SECRET')
                and os.environ.get('ENVIRON_TWITTER_USERNAME')):
            _LOGGER.debug('Enabling Twitter integration')

            return True

        _LOGGER.debug('Twitter integration disabled')
        return False

    @staticmethod
    async def async_client(api_key: str = None, key_secret: str = None):
        '''
        Factory for async Twitter instance
        '''

        twit = Twitter(api_key=api_key, key_secret=key_secret)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    'https://api.twitter.com/oauth2/token',
                    auth=aiohttp.BasicAuth(twit.api_key, twit.key_secret),
                    data={'grant_type': 'client_credentials'}) as response:
                if response.status != 200:
                    raise RuntimeError('Failed to get bearer token')

                data = await response.json()
                twit.bearer_token = data['access_token']

        twit.client = TweepyAsyncClient(
            bearer_token=twit.bearer_token, wait_on_rate_limit=True,
        )

        twit.client.user_agent = 'Byoda Twitter Client'

        return twit

    async def get_user(self, id: str = None, username: str = None
                       ) -> tweepy.User:
        '''
        Get user data from Twitter
        '''

        if not id and not username:
            username = os.environ[ENVIRON_TWITTER_USERNAME]

        response = await self.client.get_user(
            id=id, username=username, user_fields=USER_FIELDS
        )

        user = response.data

        return user

    async def get_tweets(self):
        '''
        Get user's tweets from Twitter
        '''
        client = tweepy.Client(self.bearer_token)
        public_tweets = client.get_users_tweets(self.username).data
        return public_tweets

    def extract_user_data(self, user: tweepy.User) -> Dict:
        '''
        Updates the Byoda data for the user

        returns: dict with keys matching the 'twitter_person' dict in the
        address book service contract
        '''

        data = {}
        for field, twitter_field in FIELDS_MAPPINGS.items():
            if not twitter_field or user.data.get(twitter_field) is None:
                continue
            data[field] = user.data.get(twitter_field)

        data['created_at'] = dateutil_parse(user.data['created_at'])

        entities = user.data.get('entities')
        if entities and entities.get('url'):
            urls = entities['url'].get('urls')
            if urls and len(urls):
                data['display_url'] = urls[0].get('display_url')
                data['url'] = urls[0].get('expanded_url')

        public_metrics = user.data.get('public_metrics')
        if public_metrics:
            data['followers_count'] = public_metrics.get('followers_count')
            
        data['following_count'] = public_metrics.get('following_count')
        data['tweet_count'] = public_metrics.get('tweet_count')
        data['listed_count'] = public_metrics.get('listed_count')
