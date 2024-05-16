#!/usr/bin/env python3

import sys
import unittest

from uuid import UUID, uuid4
from datetime import UTC
from datetime import datetime

from redis import Redis

from byoda.util.logger import Logger

from byotubesvr.models.lite_api_models import NetworkLinkResponseModel

from byotubesvr.database.network_link_store import NetworkLinkStore

REDIS_URL: str = \
    'redis://192.168.1.13:6379?decode_responses=True&db=1&protocol=3'

LITE = None


class TestLiteStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        client: Redis[bytes] = Redis.from_url(REDIS_URL)
        client.flushall()

        global LITE
        LITE = NetworkLinkStore(REDIS_URL)

    async def asyncTearDown(self) -> None:
        await LITE.close()

    async def test_lite_store(self) -> None:
        lite: NetworkLinkStore = LITE

        lite_id: UUID = uuid4()

        links: list[dict[str, str | list[str]]] = []
        counter: int
        for counter in range(0, 10):
            member_id: UUID = uuid4()
            link_data: dict[str, str | list[str]] = {
                'created_timestamp': datetime.now(tz=UTC).timestamp(),
                'member_id': str(member_id),
                'relation': f'friend-{counter}',
                'annotations': set(['test'])
            }
            links.append(link_data)
            network_link_id: UUID = await lite.add_link(
                lite_id, member_id, f'friend-{counter}', set(['test'])
            )
            self.assertIsNotNone(network_link_id)

        results: list[NetworkLinkResponseModel] = await lite.get_links(lite_id)
        self.assertEqual(len(results), 10)

        member_id: UUID = UUID(links[5]['member_id'])
        results = await lite.get_links(lite_id, remote_member_id=member_id)
        self.assertEqual(len(results), 1)
        link: NetworkLinkResponseModel = results[0]
        self.assertEqual(link.member_id, member_id)

        relation: str = links[5]['relation']
        results = await lite.get_links(lite_id, relation=relation)
        self.assertEqual(len(results), 1)
        link = results[0]
        self.assertEqual(link.relation, relation)

        results = await lite.get_links(
            lite_id, remote_member_id=member_id, relation=relation
        )
        self.assertEqual(len(results), 1)
        link = results[0]
        self.assertEqual(link.relation, relation)
        self.assertEqual(link.member_id, member_id)

        network_link_id = link.network_link_id
        result: int = await lite.remove_link(lite_id, network_link_id)
        self.assertEqual(result, 1)
        results = await lite.get_links(lite_id, remote_member_id=member_id)
        self.assertEqual(len(results), 0)

        # Add/remove annotations from existing link
        results = await lite.get_links(lite_id)
        self.assertEqual(len(results), 9)
        network_link_id: UUID = results[0].network_link_id
        member_id = UUID(links[0]['member_id'])
        annotations: set[str] = link.annotations | set(['creator'])
        await lite.add_link(lite_id, member_id, 'friend-0', annotations)

        results: list[NetworkLinkResponseModel] = await lite.get_links(lite_id)
        self.assertEqual(len(results), 9)
        for link in results:
            if link.network_link_id == network_link_id:
                self.assertEqual(len(link.annotations), 2)
                break

        await lite.remove_creator(lite_id, member_id, 'friend-0', 'test')
        results: list[NetworkLinkResponseModel] = await lite.get_links(lite_id)
        self.assertEqual(len(results), 9)
        for link in results:
            if link.network_link_id == network_link_id:
                self.assertEqual(len(link.annotations), 1)
                self.assertEqual(link.annotations, set(['creator']))
                break

        await lite.remove_creator(lite_id, member_id, 'friend-0', 'creator')
        results: list[NetworkLinkResponseModel] = await lite.get_links(lite_id)
        self.assertEqual(len(results), 8)

        # Test de-dupe
        link = results[0]
        data: dict[str, str | list[str]] = {
            'created_timestamp': link.created_timestamp.timestamp(),
            'member_id': str(link.member_id),
            'relation': link.relation,
            'annotations': ['dummy'],
            'network_link_id': str(uuid4())
        }
        key: str = NetworkLinkStore.get_key(lite_id)
        await lite.client.json().arrappend(key, '$', data)
        results: list[NetworkLinkResponseModel] = await lite.get_links(lite_id)
        self.assertEqual(len(results), 9)
        filtered_results: list[NetworkLinkResponseModel] = [
            result for result in results
            if result.member_id == link.member_id
            and result.relation == link.relation
        ]
        annotations = await lite._dedupe(
            lite_id, link.member_id, link.relation, filtered_results
        )
        self.assertEqual(len(annotations), 2)
        self.assertEqual(annotations, set(['dummy', 'test']))
        results: list[NetworkLinkResponseModel] = await lite.get_links(lite_id)
        self.assertEqual(len(results), 8)

        for result in results:
            if result.network_link_id == link.network_link_id:
                # dedupe() doesn't update the remaining entry itself so in
                # this test the annotations in the remaining entry should
                # still be ['test']
                self.assertEqual(result.annotations, set(['test']))

        print('hoi')


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
