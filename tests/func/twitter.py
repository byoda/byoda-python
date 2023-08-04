#!/usr/bin/env python3

'''
Import data from Twitter and add it to the data for a service

Requires enabling Twitter Development API. Sign up at
https://developer.twitter.com/en

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''
import os
import sys
import unittest
import asyncio

import requests

from multiprocessing import Process
import uvicorn

from byoda.util.fastapi import setup_api

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema

from byoda.datatypes import GRAPHQL_API_URL_PREFIX
from byoda.datatypes import IdType

from byoda.data_import.twitter import Twitter
from byoda.data_import.twitter import ENVIRON_TWITTER_USERNAME
from byoda.data_import.twitter import ENVIRON_TWITTER_API_KEY
from byoda.data_import.twitter import ENVIRON_TWITTER_KEY_SECRET

from byoda.util.logger import Logger
from byoda.util.api_client.graphql_client import GraphQlClient

from byoda import config

from podserver.routers import account as AccountRouter
from podserver.routers import member as MemberRouter
from podserver.routers import authtoken as AuthTokenRouter

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account

from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.addressbook_queries import APPEND_TWEETS, QUERY_TWEETS
from tests.lib.addressbook_queries import APPEND_TWITTER_MEDIAS
from tests.lib.addressbook_queries import MUTATE_TWITTER_ACCOUNT

TEST_DIR = '/tmp/byoda-tests/twitter'
TWITTER_API_KEY_FILE = 'tests/collateral/local/twitter_api_key'
TWITTER_KEY_SECRET_FILE = 'tests/collateral/local/twitter_key_secret'

# TWITTER_USERNAME = 'byoda_org'
TWITTER_USERNAME = 'profgalloway'


class TestTwitterIntegration(unittest.IsolatedAsyncioTestCase):
    PROCESS = None
    APP_CONFIG = None

    async def asyncSetUp(self):
        network_data = await setup_network(TEST_DIR)
        pod_account = await setup_account(network_data)
        global BASE_URL
        BASE_URL = BASE_URL.format(PORT=config.server.HTTP_PORT)

        app = setup_api(
            'Byoda test pod', 'server for testing pod APIs',
            'v0.0.1',
            [AccountRouter, MemberRouter, AuthTokenRouter],
            lifespan=None
        )

        for account_member in pod_account.memberships.values():
            account_member.enable_graphql_api(app)
            await account_member.update_registration()

        TestTwitterIntegration.PROCESS = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={
                'host': '0.0.0.0',
                'port': config.server.HTTP_PORT,
                'log_level': 'trace'
            },
            daemon=True
        )
        TestTwitterIntegration.PROCESS.start()

        await asyncio.sleep(3)

    @classmethod
    async def asyncTearDown(self):

        TestTwitterIntegration.PROCESS.terminate()

    async def test_twitter_apis(self):
        schema = await Schema.get_schema(
            'addressbook.json', config.server.network.paths.storage_driver,
            None, None, verify_contract_signatures=False
        )

        data = {}
        twit = Twitter.client()

        #
        # Get the info about the user
        #
        user = twit.get_user()
        userdata = twit.extract_user_data(user)
        data['twitter_account'] = userdata

        #
        # See if we can send the Twitter account info to the pod
        #
        pod_account: Account = config.server.account
        account_member: Member = \
            pod_account.memberships[ADDRESSBOOK_SERVICE_ID]

        data = {
            'username': str(account_member.member_id)[:8],
            'password': os.environ['ACCOUNT_SECRET'],
            'service_id': ADDRESSBOOK_SERVICE_ID,
            'target_type': IdType.MEMBER.value,
        }
        response = requests.post(
            f'{BASE_URL}/v1/pod/authtoken', json=data
        )
        data = response.json()
        member_auth_header = {
            'Authorization': f'bearer {data["auth_token"]}',
        }

        url = BASE_URL.rstrip('api/')
        url = url + GRAPHQL_API_URL_PREFIX.format(
            service_id=account_member.service_id
        )

        resp = GraphQlClient.call_sync(
            url, MUTATE_TWITTER_ACCOUNT, vars=userdata,
            headers=member_auth_header
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data['data'])
        self.assertIsNone(data.get('errors'))

        #
        # Get some tweets to test pagination
        #
        all_tweets, referencing_tweets, media = twit.get_tweets(
            with_related=False
        )
        start = 20
        since_id = all_tweets[start]['asset_id']
        subset_tweets, referencing_tweets, medias = twit.get_tweets(
            since_id=since_id, with_related=False
        )
        self.assertEqual(len(subset_tweets), start)

        #
        # Put the tweets and media in the pod
        #
        for tweet in all_tweets + referencing_tweets:
            resp = GraphQlClient.call_sync(
                url, APPEND_TWEETS, vars=tweet, headers=member_auth_header
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsNotNone(data['data'])
            self.assertIsNone(data.get('errors'))

        for media in medias:
            resp = GraphQlClient.call_sync(
                url, APPEND_TWITTER_MEDIAS, vars=media,
                headers=member_auth_header
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsNotNone(data['data'])
            self.assertIsNone(data.get('errors'))

        # Now get the tweets back from the pod
        resp = GraphQlClient.call_sync(
            url, QUERY_TWEETS, headers=member_auth_header
        )

        data = resp.json()
        edges = data['data']['tweets_connection']['edges']
        self.assertEqual(len(edges), len(all_tweets))

        all_tweets, referencing_tweets, media = twit.get_tweets(
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
