#!/usr/bin/env python3

'''
Import data from Twitter and add it to the data for a service

Requires enabling Twitter Development API. Sign up at
https://developer.twitter.com/en

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''
import os
import sys
import unittest
import asyncio

from byoda.datamodel.schema import Schema

from byoda.data_import.twitter import Twitter
from byoda.data_import.twitter import ENVIRON_TWITTER_USERNAME
from byoda.data_import.twitter import ENVIRON_TWITTER_API_KEY
from byoda.data_import.twitter import ENVIRON_TWITTER_KEY_SECRET

from byoda.util.logger import Logger

from byoda import config

from tests.lib.setup import setup_network

TEST_DIR = '/tmp/byoda-tests/twitter'
TWITTER_API_KEY_FILE = 'tests/collateral/local/twitter_api_key'
TWITTER_KEY_SECRET_FILE = 'tests/collateral/local/twitter_key_secret'

# TWITTER_USERNAME = 'byoda_org'
TWITTER_USERNAME = 'profgalloway'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def test_twitter_apis(self):
        schema = await Schema.get_schema(
            'addressbook.json', config.server.network.paths.storage_driver,
            None, None, verify_contract_signatures=False
        )

        data = {}
        twit = Twitter.client()

        user = await twit.get_user()
        data['twitter_account'] = twit.extract_user_data(user)

        all_tweets, referencing_tweets, media = await twit.get_tweets(
            with_related=True
        )

        data['tweets'] = all_tweets
        data['tweets'].extend(referencing_tweets)
        data['twitter_media'] = media

        schema.validator.is_valid(data)

        media_keys = set(
            [media['media_key'] for media in data['twitter_media']]
        )
        media_found = 0
        media_not_found = 0
        for tweet in data['tweets']:
            for media_key in tweet.get('media_keys', []):
                if media_key in media_keys:
                    media_found += 1
                else:
                    media_not_found += 1

        self.assertGreater(media_found, media_not_found)

        all_tweets, referencing_tweets, media = await twit.get_tweets(
            with_related=False
        )
        self.assertGreater(len(all_tweets), 10)
        start = 20
        since_id = all_tweets[start]['asset_id']
        subset_tweets, referencing_tweets, media = await twit.get_tweets(
            since_id=since_id, with_related=False
        )
        self.assertEqual(len(subset_tweets), start)


async def main():
    with open(TWITTER_API_KEY_FILE, 'r') as file_desc:
        api_key = file_desc.read().strip()

    with open(TWITTER_KEY_SECRET_FILE, 'r') as file_desc:
        key_secret = file_desc.read().strip()

    os.environ[ENVIRON_TWITTER_USERNAME] = TWITTER_USERNAME
    os.environ[ENVIRON_TWITTER_API_KEY] = api_key
    os.environ[ENVIRON_TWITTER_KEY_SECRET] = key_secret

    await setup_network(TEST_DIR)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    asyncio.run(main())

    unittest.main()
