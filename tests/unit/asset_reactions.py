#!/usr/bin/env python3

'''
Test cases for BYO.Tube-lite asset reactions

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import sys
import unittest

from time import sleep
from datetime import UTC
from datetime import datetime
from uuid import UUID
from logging import Logger

from redis import Redis
import redis.asyncio as redis

from byotubesvr.models.lite_api_models import AssetReactionRequestModel
from byotubesvr.models.lite_api_models import AssetReactionResponseModel
from tests.lib.util import get_test_uuid

from byotubesvr.database.asset_reaction_store import AssetReactionStore

from byoda.util.logger import Logger as ByodaLogger

REDIS_URL: str = 'redis://192.168.1.13:6379/0?decode_responses=True&protocol=3'

REDIS_CLIENT: Redis | None = None
ASSET_REACTION_STORE: AssetReactionStore | None = None


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    @classmethod
    async def asyncSetUp(cls) -> None:
        global REDIS_CLIENT
        REDIS_CLIENT = redis.from_url(REDIS_URL)
        await REDIS_CLIENT.flushall()

        global ASSET_REACTION_STORE
        ASSET_REACTION_STORE = AssetReactionStore(REDIS_URL)

    @classmethod
    async def asyncTearDown(cls) -> None:
        await REDIS_CLIENT.aclose()
        await ASSET_REACTION_STORE.close()

    async def test_reactions_list(self) -> None:
        store: AssetReactionStore = ASSET_REACTION_STORE
        lite_id: UUID = get_test_uuid()

        reactions: list[AssetReactionRequestModel] = []
        for counter in range(0, 100):
            member_id: UUID = get_test_uuid()
            asset_id: UUID = get_test_uuid()

            reaction_model = AssetReactionRequestModel(
                member_id=member_id, asset_id=asset_id,
                asset_url=f'https://video-{counter}/',
                asset_class='public_assets',
                relation=f'like-{counter}', bookmark=str(counter)
            )
            reactions.append(reaction_model)
            await store.add_reaction(lite_id, reaction_model)

        results: list[AssetReactionResponseModel] = \
            await store.get_reactions(lite_id)
        self.assertEqual(len(results), 21)

        reaction_key: str
        _: str
        delete_list: list[int] = [
            1, 12, 23, 34, 35, 36, 37, 45, 49, 80, 88, 89, 91, 99
        ]
        for item in delete_list:
            reaction_key, _ = AssetReactionStore._get_keys(
                lite_id, reactions[item].member_id, reactions[item].asset_id
            )
            # We delete the (JSON) key, but we don't remove it from the
            # ordered set
            await store.client.delete(reaction_key)

        after: str
        after, _ = AssetReactionStore._get_keys(
            lite_id, reactions[95].member_id, reactions[95].asset_id
        )
        results: list[AssetReactionResponseModel] = \
            await store.get_reactions(lite_id, first=12, after=after)
        self.assertEqual(len(results), 13)
        self.assertEqual(results[0].member_id, reactions[94].member_id)
        self.assertEqual(results[1].member_id, reactions[93].member_id)
        self.assertEqual(results[2].member_id, reactions[92].member_id)
        self.assertEqual(results[3].member_id, reactions[90].member_id)
        self.assertEqual(results[4].member_id, reactions[87].member_id)
        self.assertEqual(results[5].member_id, reactions[86].member_id)
        self.assertEqual(results[6].member_id, reactions[85].member_id)
        self.assertEqual(results[7].member_id, reactions[84].member_id)
        self.assertEqual(results[8].member_id, reactions[83].member_id)
        self.assertEqual(results[9].member_id, reactions[82].member_id)
        self.assertEqual(results[10].member_id, reactions[81].member_id)
        self.assertEqual(results[11].member_id, reactions[79].member_id)
        self.assertEqual(results[12].member_id, reactions[78].member_id)

        # Bogus cursor because we take member_id and asset_ids from
        # different reactions
        after, _ = AssetReactionStore._get_keys(
            lite_id, reactions[95].member_id, reactions[94].asset_id
        )
        results: list[AssetReactionResponseModel] = \
            await store.get_reactions(lite_id, first=12, after=after)
        self.assertEqual(len(results), 0)

        # Not a bogus cursor because while the (JSON) key for item 99 was,
        # we did not delete the ordered set entry
        after, _ = AssetReactionStore._get_keys(
            lite_id, reactions[99].member_id, reactions[99].asset_id
        )
        results: list[AssetReactionResponseModel] = \
            await store.get_reactions(lite_id, first=17, after=after)
        self.assertEqual(len(results), 18)

        result: int = await store.delete_reaction(
            lite_id, reactions[99].member_id, reactions[99].asset_id
        )
        # We already deleted the JSON key so the result will be 0,
        # eventhough we removed an item from the ordered set
        self.assertEqual(result, 0)

        # Now the item is removed from the ordered set, we should now
        # get an empty list
        results: list[AssetReactionResponseModel] = \
            await store.get_reactions(lite_id, first=17, after=after)
        self.assertEqual(len(results), 0)

        after, _ = AssetReactionStore._get_keys(
            lite_id, reactions[5].member_id, reactions[5].asset_id
        )
        results: list[AssetReactionResponseModel] = \
            await store.get_reactions(lite_id, first=12, after=after)
        self.assertEqual(len(results), 4)

        after, _ = AssetReactionStore._get_keys(
            lite_id, reactions[98].member_id, reactions[98].asset_id
        )
        results: list[AssetReactionResponseModel] = \
            await store.get_reactions(lite_id, first=17, after=after)
        self.assertEqual(len(results), 18)

    async def test_asset_reaction_store(self) -> None:
        store: AssetReactionStore = ASSET_REACTION_STORE
        lite_id: UUID = get_test_uuid()
        member_id: UUID = get_test_uuid()
        asset_id: UUID = get_test_uuid()
        with self.assertRaises(FileNotFoundError):
            await store.get_reaction(lite_id, member_id, asset_id)

        reaction_model = AssetReactionRequestModel(
            member_id=member_id, asset_id=asset_id,
            asset_url='https://video/', asset_class='public_assets',
            relation='like', bookmark='96'
        )
        await store.add_reaction(lite_id, reaction_model)

        response_model: AssetReactionResponseModel | None = \
            await store.get_reaction(lite_id, member_id, asset_id)

        self.assertIsNotNone(response_model)
        self.assertEqual(member_id, response_model.member_id)
        asset_timestamp: float = response_model.created_timestamp.timestamp()

        sorted_set_key: str
        _: str
        _, sorted_set_key = AssetReactionStore._get_keys(
            lite_id, member_id, asset_id
        )
        count: int = await store.client.zcount(sorted_set_key, '-inf', '+inf')
        self.assertEqual(count, 1)

        reaction: AssetReactionResponseModel | None = \
            await store.get_reaction(lite_id, member_id, asset_id)
        self.assertEqual(member_id, reaction.member_id)
        self.assertEqual(asset_id, reaction.asset_id)
        self.assertEqual('https://video/', str(reaction.asset_url))
        self.assertEqual('public_assets', reaction.asset_class)
        self.assertEqual('like', reaction.relation)
        self.assertEqual('96', reaction.bookmark)

        await store.add_reaction(lite_id, reaction_model)

        response_model: AssetReactionResponseModel | None = \
            await store.get_reaction(lite_id, member_id, asset_id)

        self.assertIsNotNone(response_model)
        self.assertEqual(member_id, response_model.member_id)
        self.assertGreater(
            response_model.created_timestamp.timestamp(), asset_timestamp
        )

        result: int = await store.delete_reaction(lite_id, member_id, asset_id)
        self.assertEqual(result, 1)

        count: int = await store.client.zcount(sorted_set_key, '-inf', '+inf')
        self.assertEqual(count, 0)

        with self.assertRaises(FileNotFoundError):
            await store.get_reaction(lite_id, member_id, asset_id)

    async def test_asset_reactions(self) -> None:
        client: Redis = REDIS_CLIENT
        sorted_set_key: str = 'sorted_set'

        for count in range(0, 100):
            # Increase time as the sorted set of asset reactions gets
            # sorted on timestamp
            sleep(0.001)

            timestamp: float = datetime.now(tz=UTC).timestamp()
            data: dict[str, str] = {
                'created_timestamp': timestamp,
                'key': f'key-{count}',
                'value': f'value-{count}'

            }
            cursor: str = f'{data["key"]}-{data["value"]}'
            await client.hset(cursor, mapping=data)
            await client.zadd(sorted_set_key, {cursor: timestamp})

        await client.delete('key-55-value-55')
        await client.delete('key-49-value-49')

        step: int = 10
        first: int = 15
        after: str = 'key-58-value-58'
        cursor_found: bool = False
        results: list[dict] = []
        start_index: int = 0
        removals: list[str] = []
        while True:
            cursors: list[str] = await client.zrevrange(
                sorted_set_key,
                start_index,
                start_index + step - 1
            )
            for cursor in cursors:
                if not cursor_found and cursor == after:
                    cursor_found = True
                    continue

                if cursor_found:
                    data: dict[str, str] = await client.hgetall(cursor)
                    if data:
                        results.append(data)
                    else:
                        removals.append(cursor)

                    if len(results) == first:
                        break

            # Delete items in the sorted set for which the key was not found
            if removals:
                await client.zrem(sorted_set_key, *removals)
                # Next time we request the next set of cursors, we need to
                # adjust the start index by the number elements removed
                start_index -= len(removals)
                removals = []

            if len(cursors) < step:
                break

            if len(results) == first:
                break

            start_index += step

        for result in results:
            print(f'{result}')

        self.assertEqual(len(results), 15)

        check: list[str] = await client.zrange(sorted_set_key, 0, -1)
        self.assertEqual(len(check), 98)


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )
    unittest.main()
