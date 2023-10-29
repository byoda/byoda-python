'''
Test cases for Sqlite storage

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import time
import unittest
from copy import deepcopy
from uuid import UUID
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone

from byoda.datamodel.schema import Schema
from byoda.datamodel.account import Account
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.table import QueryResult

from byoda.datatypes import MemberStatus

from byoda.datastore.data_store import DataStore

from byoda.storage.sqlite import SqliteStorage

from byoda.servers.pod_server import PodServer

from byoda import config

from byoda.util.logger import Logger

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account

from tests.lib.util import get_test_uuid

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

NETWORK = config.DEFAULT_NETWORK
SCHEMA = 'tests/collateral/addressbook.json'

TEST_DIR = '/tmp/byoda-tests/sqlite'


@dataclass(slots=True)
class NetworkInvite:
    created_timestamp: str
    member_id: str
    relation: str
    text: str

    @staticmethod
    def from_dict(data: dict) -> 'NetworkInvite':
        local_data = deepcopy(data)
        if isinstance(local_data['member_id'], UUID):
            local_data['member_id'] = str(data['member_id'])
        if isinstance(local_data['created_timestamp'], datetime):
            local_data['created_timestamp'] = \
                local_data['created_timestamp'].isoformat()

        return NetworkInvite(
            local_data['created_timestamp'],
            local_data['member_id'],
            local_data['relation'],
            local_data['text']
        )


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock_environment_vars(TEST_DIR)
        network_data = await setup_network()
        account: Account = await setup_account(network_data)

        config.test_case = "TEST_CLIENT"
        config.disable_pubsub = True

        server: PodServer = config.server
        data_store: DataStore = server.data_store

        for member in account.memberships.values():
            await member.create_query_cache()
            await member.create_counter_cache()
            schema: Schema = member.schema
            schema.get_data_classes()

            await data_store.setup_member_db(
                member.member_id, member.service_id, schema
            )

    async def test_object(self):
        server: PodServer = config.server
        data_store: DataStore = server.data_store
        account: Account = server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member = await account.get_membership(service_id)
        uuid: UUID = member.member_id

        now = datetime.now(timezone.utc)

        sql = data_store.backend

        # Populate Person object with string data and check the result
        person_table = sql.member_sql_tables[uuid]['person']
        given_name = 'Steven'
        family_name = 'Hessing'
        await person_table.mutate(
            {
                'family_name': family_name,
                'given_name': given_name
            },
            '', None, None, None
        )

        result: list[QueryResult] = await person_table.query()
        self.assertEqual(len(result), 1)
        data, _ = result[0]
        self.assertEqual(len(data), 6)
        self.assertEqual(given_name, data['given_name'])
        self.assertEqual(family_name, data['family_name'])
        self.assertEqual(data['email'], None)

        # Populate Member object with datetime and UUID data and check the
        # result
        member_table = sql.member_sql_tables[uuid]['member']
        await member_table.mutate(
            {
                'member_id': uuid,
                'joined': now
            },
            '', None, None, None
        )
        result: list[QueryResult] = await member_table.query()
        self.assertEqual(len(result), 1)
        data, _ = result[0]
        self.assertEqual(data['member_id'], uuid)
        self.assertEqual(data['joined'], now)

    async def test_array(self):
        server: PodServer = config.server
        data_store: DataStore = server.data_store
        account: Account = server.account
        service_id: int = ADDRESSBOOK_SERVICE_ID
        member = await account.get_membership(service_id)
        uuid: UUID = member.member_id

        now = datetime.now(timezone.utc)

        sql = data_store.backend

        # Test for NetworkInvites array of objects
        network_invites_table = sql.member_sql_tables[uuid]['network_invites']
        network_invites: list[NetworkInvite] = []

        # Append network invite
        network_invite = NetworkInvite(
            now.isoformat(), str(get_test_uuid()), "friend",
            "am I a friend of yours?"
        )
        network_invites.append(network_invite)
        await network_invites_table.append(
            {
                'created_timestamp': network_invites[0].created_timestamp,
                'member_id': network_invites[0].member_id,
                'relation': network_invites[0].relation,
                'text': network_invites[0].text,
            },
            '', None, None, None
        )
        data: list[QueryResult] = await network_invites_table.query()
        self.assertEqual(len(data), 1)
        if not compare_network_invite(data, network_invites):
            raise self.assertTrue(False)

        # Append another network invite
        time.sleep(1)
        now = datetime.now(timezone.utc)

        network_invite = NetworkInvite(
            now.isoformat(), str(get_test_uuid()), "family", "am I family?"
        )
        network_invites.append(network_invite)
        await network_invites_table.append(
            {
                'created_timestamp': network_invites[1].created_timestamp,
                'member_id': network_invites[1].member_id,
                'relation': network_invites[1].relation,
                'text': network_invites[1].text,
            },
            '', None, None, None
        )
        data: list[QueryResult] = await network_invites_table.query()
        self.assertEqual(len(data), 2)
        if not compare_network_invite(data, network_invites):
            raise self.assertTrue(False)

        # Append another network invite
        time.sleep(1)
        now = datetime.now(timezone.utc)

        network_invite = NetworkInvite(
            now.isoformat(), str(get_test_uuid()),
            "colleague", "do I work with you?"
        )
        network_invites.append(network_invite)

        await network_invites_table.append(
            {
                'created_timestamp': network_invites[2].created_timestamp,
                'member_id': network_invites[2].member_id,
                'relation': network_invites[2].relation,
                'text': network_invites[2].text,
            },
            '', None, None, None
        )
        data: list[QueryResult] = await network_invites_table.query()
        self.assertEqual(len(data), 3)

        data: list[QueryResult] = await network_invites_table.query()
        self.assertEqual(len(data), 3)
        if compare_network_invite(data, network_invites) != 3:
            raise self.assertTrue(False)

        # filter on datetime
        filters = {
            'created_timestamp': {
                'atbefore': datetime.fromisoformat(
                    network_invites[1].created_timestamp
                )
            }
        }
        data_filters = DataFilterSet(filters)
        data: list[QueryResult] = await network_invites_table.query(
            data_filters=data_filters
        )
        self.assertEqual(len(data), 2)
        if compare_network_invite(data, network_invites) != 2:
            raise self.assertTrue(False)

        # filter on 2 datetime criteria
        filters = {
            'created_timestamp': {
                'atafter': datetime.fromisoformat(
                    network_invites[1].created_timestamp
                ),
                'atbefore': datetime.fromisoformat(
                    network_invites[1].created_timestamp
                )
            }
        }
        data_filters = DataFilterSet(filters)
        data: list[QueryResult] = await network_invites_table.query(
            data_filters=data_filters
        )
        self.assertEqual(len(data), 1)
        if compare_network_invite(data, network_invites) != 1:
            raise self.assertTrue(False)

        # Filter on datetime and string
        filters = {
            'created_timestamp': {
                'atafter': datetime.fromisoformat(
                    network_invites[1].created_timestamp
                )
            },
            'relation': {
                'eq': 'family'
            }
        }
        data_filters = DataFilterSet(filters)
        data: list[QueryResult] = await network_invites_table.query(
            data_filters=data_filters
        )
        self.assertEqual(len(data), 1)
        if compare_network_invite(data, network_invites) != 1:
            raise self.assertTrue(False)

        #
        # filter 'ne' str
        filters = {
            'relation': {
                'ne': 'family'
            }
        }
        data_filters = DataFilterSet(filters)
        data: list[QueryResult] = await network_invites_table.query(
            data_filters=data_filters
        )
        self.assertEqual(len(data), 2)
        if compare_network_invite(data, network_invites) != 2:
            raise self.assertTrue(False)

        #
        # filter 'eq' UUID
        #
        filters = {
            'member_id': {
                'eq': network_invites[2].member_id
            }
        }
        data_filters = DataFilterSet(filters)
        results: list[QueryResult] = await network_invites_table.query(
            data_filters=data_filters
        )
        self.assertEqual(len(results), 1)

        if compare_network_invite(results, network_invites) != 1:
            raise self.assertTrue(False)

        data, _ = results[0]
        self.assertEqual(
            UUID(network_invites[2].member_id), data['member_id']
        )

        #
        # filter 'ne' UUID
        #
        filters = {
            'member_id': {
                'ne': network_invites[2].member_id
            }
        }
        data_filters = DataFilterSet(filters)
        results: list[QueryResult] = await network_invites_table.query(
            data_filters=data_filters
        )
        self.assertEqual(len(results), 2)

        if compare_network_invite(results, network_invites) != 2:
            raise self.assertTrue(False)

        data, _ = results[0]
        self.assertNotEqual(
            UUID(network_invites[2].member_id), data['member_id']
        )

        data, _ = results[1]
        self.assertNotEqual(
            UUID(network_invites[2].member_id), data['member_id']
        )

        #
        # Update network invite #1
        #
        time.sleep(1)
        now = datetime.now(timezone.utc)

        network_invites.append(network_invite)

        await network_invites_table.update(
            {
                'text': 'updated text'
            }, '', data_filters, None, None, None
        )
        filters = {
            'created_timestamp': {
                'atafter': datetime.fromisoformat(
                    network_invites[1].created_timestamp
                )
            },
            'relation': {
                'eq': 'family'
            }
        }
        data_filters = DataFilterSet(filters)
        results: list[QueryResult] = await network_invites_table.query(
            data_filters=data_filters
        )
        self.assertEqual(len(results), 1)

        data, _ = results[0]
        self.assertEqual(data['text'], 'updated text')

        data = {
            '_created_timestamp': 1671989969.329426,
            '_relation': 'family',
        }
        stmt = (
            'SELECT * FROM _network_invites '
            'WHERE _created_timestamp >= :_created_timestamp '
            'AND _relation = :_relation'
        )
        data = await network_invites_table.sql_store.execute(
            stmt, member_id=network_invites_table.member_id, data=data,
            autocommit=True, fetchall=True
        )

        results = []
        for row in data:
            result = {}
            for column_name in row.keys():
                if not column_name.startswith('_'):
                    continue
                field_name = column_name.lstrip('_')
                result[field_name] = \
                    network_invites_table.columns[field_name].normalize(
                        row[column_name]
                    )
            results.append(result)

        self.assertEqual(len(results), 1)

        #
        # Delete network invites with relation = 'family'
        #
        filters = {
            'relation': {
                'eq': 'family'
            }
        }
        data_filters = DataFilterSet(filters)
        data = await network_invites_table.delete(data_filters=data_filters)

        data: list[QueryResult] = await network_invites_table.query(
            data_filters=data_filters
        )
        self.assertIsNone(data)

        data = await network_invites_table.query()
        self.assertEqual(len(data), 2)

        #
        # Delete all network invites
        #
        data = await network_invites_table.delete(data_filters={})

        data = await network_invites_table.query()
        self.assertIsNone(data)

    async def test_member_db(self):
        config.test_case = "TEST_CLIENT"
        account: Account = config.server.account

        # BUG: async unittest.asyncsetup did not run??
        os.remove(
            '/tmp/byoda-tests/sqlite'
            '/private/network-byoda.net/account-pod/data/account.db'
        )
        schema = await Schema.get_schema(
            'addressbook.json', config.server.network.paths.storage_driver,
            None, None, verify_contract_signatures=False
        )
        schema.get_data_classes()

        uuid = get_test_uuid()

        # '/tmp/byoda-tests/sqlite/private/network-byoda.net/account-pod/data/account.db'
        sql = await SqliteStorage.setup(config.server, account.data_secret)
        await sql.setup_member_db(uuid, schema.service_id)
        await sql.set_membership_status(
            uuid, schema.service_id, MemberStatus.ACTIVE
        )
        memberships = await sql.get_memberships()
        self.assertEqual(len(memberships), 1)

        await sql.set_membership_status(
            uuid, schema.service_id, MemberStatus.PAUSED
        )
        memberships = await sql.get_memberships()
        self.assertEqual(len(memberships), 1)

        memberships = await sql.get_memberships(status=MemberStatus.PAUSED)
        self.assertEqual(len(memberships), 1)

        await sql.set_membership_status(
            uuid, schema.service_id, MemberStatus.ACTIVE
        )
        memberships = await sql.get_memberships(status=MemberStatus.PAUSED)
        self.assertEqual(len(memberships), 1)

        memberships = await sql.get_memberships(status=MemberStatus.ACTIVE)
        self.assertEqual(len(memberships), 1)

        memberships = await sql.get_memberships()
        self.assertEqual(len(memberships), 1)


def compare_network_invite(data: list[QueryResult],
                           network_invites: list[NetworkInvite]) -> int:
    '''
    Check how often a '''
    found = 0
    for value, _ in data:
        invite = NetworkInvite.from_dict(value)
        if invite in network_invites:
            found += 1

    return found


if __name__ == '__main__':
    Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
