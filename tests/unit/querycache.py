'''
Test cases for Query ID cache

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import shutil
import unittest

from byoda.util.logger import Logger

from byoda.datamodel.member import Member

from byoda.datastore.querycache import QueryCache

from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import get_test_uuid

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

TEST_DIR = '/tmp/byoda-tests/query_cache'


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

    @classmethod
    async def asyncTearDown(self):
        pass

    async def test_query_cache(self):
        network_data = await setup_network(TEST_DIR)
        pod_account = await setup_account(network_data)
        member: Member = pod_account.memberships[ADDRESSBOOK_SERVICE_ID]

        cache: QueryCache = await QueryCache.create(member)

        query_id = get_test_uuid()
        remote_member_id = get_test_uuid()
        self.assertFalse(await cache.exists(query_id))
        self.assertFalse(await cache.delete(query_id))

        self.assertTrue(await cache.set(query_id, remote_member_id))
        self.assertTrue(await cache.exists(query_id))
        self.assertFalse(await cache.set(query_id, remote_member_id))

        self.assertTrue(await cache.delete(query_id))
        self.assertFalse(await cache.exists(query_id))

        self.assertEqual(await cache.purge(), 0)

        await cache.close()


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
