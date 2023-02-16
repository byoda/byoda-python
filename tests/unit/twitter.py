#!/usr/bin/env python3

'''
Test cases for importing tweets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import unittest
import asyncio

# import tweepy

from byoda.data_import.twitter import Twitter
from byoda.data_import.twitter import ENVIRON_TWITTER_USERNAME
from byoda.data_import.twitter import ENVIRON_TWITTER_API_KEY
from byoda.data_import.twitter import ENVIRON_TWITTER_KEY_SECRET

from byoda.util.logger import Logger

TWITTER_API_KEY_FILE = 'tests/collateral/local/twitter_api_key'
TWITTER_KEY_SECRET_FILE = 'tests/collateral/local/twitter_key_secret'

TWITTER_USERNAME = 'byoda_org'
TWIT = None


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def test_twitter_apis(self):
        twit = Twitter.client()
        user = await twit.get_user()
        data = twit.extract_user_data(user)
        print(data)

        all_tweets = await twit.get_tweets()
        self.assertGreater(len(all_tweets), 10)
        start = 8
        since_id = all_tweets[-1 * start]['asset_id']
        subset_tweets = await twit.get_tweets(since_id=since_id)
        self.assertEqual(len(subset_tweets), len(all_tweets) - start)


async def main():
    with open(TWITTER_API_KEY_FILE, 'r') as file_desc:
        api_key = file_desc.read().strip()

    with open(TWITTER_KEY_SECRET_FILE, 'r') as file_desc:
        key_secret = file_desc.read().strip()

    os.environ[ENVIRON_TWITTER_USERNAME] = TWITTER_USERNAME
    os.environ[ENVIRON_TWITTER_API_KEY] = api_key
    os.environ[ENVIRON_TWITTER_KEY_SECRET] = key_secret

if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    asyncio.run(main())

    unittest.main()
