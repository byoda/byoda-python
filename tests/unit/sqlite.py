'''
Test cases for Sqlite storage

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import time
import shutil
import unittest
from copy import deepcopy
from uuid import UUID
from dataclasses import dataclass
from datetime import datetime, timezone

from byoda.datamodel.schema import Schema
from byoda.datamodel.network import Network
from byoda.datamodel.datafilter import DataFilterSet

from byoda.servers.pod_server import PodServer

from byoda.storage.sqlite import SqliteStorage

from byoda import config

from podserver.util import get_environment_vars

from byoda.util.logger import Logger

from tests.lib.util import get_test_uuid

NETWORK = config.DEFAULT_NETWORK
SCHEMA = 'tests/collateral/addressbook.json'

TEST_DIR = '/tmp/byoda-tests/sqlite'


@dataclass
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
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        os.makedirs(TEST_DIR)

        shutil.copy(SCHEMA, TEST_DIR)
        os.environ['ROOT_DIR'] = TEST_DIR
        os.environ['BUCKET_PREFIX'] = 'byoda'
        os.environ['CLOUD'] = 'LOCAL'
        os.environ['NETWORK'] = 'byoda.net'
        os.environ['ACCOUNT_ID'] = str(get_test_uuid())
        os.environ['ACCOUNT_SECRET'] = 'test'
        os.environ['LOGLEVEL'] = 'DEBUG'
        os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
        os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

        # Remaining environment variables used:
        network_data = get_environment_vars()

        network = Network(network_data, network_data)
        await network.load_network_secrets()
        config.server = PodServer()
        config.server.network = network

    async def test_object(self):
        schema = await Schema.get_schema(
            'addressbook.json', config.server.network.paths.storage_driver,
            None, None, verify_contract_signatures=False
        )
        schema.get_graphql_classes()

        uuid = get_test_uuid()
        now = datetime.now(timezone.utc)

        sql = await SqliteStorage.setup()
        await sql.setup_member_db(uuid, schema.service_id, schema)

        # Populate Person object with string data and check the result
        person_table = sql.member_sql_tables[uuid]['person']
        given_name = 'Steven'
        family_name = 'Hessing'
        await person_table.mutate(
            {
                'family_name': family_name,
                'given_name': given_name
            }
        )

        data = await person_table.query()
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
            }
        )
        data = await member_table.query()
        self.assertEqual(data['member_id'], uuid)
        self.assertEqual(data['joined'], now)

    async def test_array(self):
        schema = await Schema.get_schema(
            'addressbook.json', config.server.network.paths.storage_driver,
            None, None, verify_contract_signatures=False
        )
        schema.get_graphql_classes()

        uuid = get_test_uuid()
        now = datetime.now(timezone.utc)

        sql = await SqliteStorage.setup()
        await sql.setup_member_db(uuid, schema.service_id, schema)

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
            }
        )
        data = await network_invites_table.query()
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
            }
        )
        data = await network_invites_table.query()
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
            }
        )
        data = await network_invites_table.query()
        self.assertEqual(len(data), 3)

        data = await network_invites_table.query()
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
        data = await network_invites_table.query(data_filters=data_filters)
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
        data = await network_invites_table.query(data_filters=data_filters)
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
        data = await network_invites_table.query(data_filters=data_filters)
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
        data = await network_invites_table.query(data_filters=data_filters)
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
        data = await network_invites_table.query(data_filters=data_filters)
        self.assertEqual(len(data), 1)

        if compare_network_invite(data, network_invites) != 1:
            raise self.assertTrue(False)

        self.assertEqual(
            UUID(network_invites[2].member_id), data[0]['member_id']
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
        data = await network_invites_table.query(data_filters=data_filters)
        self.assertEqual(len(data), 2)

        if compare_network_invite(data, network_invites) != 2:
            raise self.assertTrue(False)

        self.assertNotEqual(
            UUID(network_invites[2].member_id), data[0]['member_id']
        )
        self.assertNotEqual(
            UUID(network_invites[2].member_id), data[1]['member_id']
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
            }, data_filters
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
        data = await network_invites_table.query(data_filters=data_filters)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['text'], 'updated text')

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

        data = await network_invites_table.query(data_filters=data_filters)
        self.assertIsNone(data)

        data = await network_invites_table.query()
        self.assertEqual(len(data), 2)

        #
        # Delete all network invites
        #
        data = await network_invites_table.delete(data_filters={})

        data = await network_invites_table.query()
        self.assertIsNone(data)


def compare_network_invite(data: list[dict[str, str]],
                           network_invites: list[NetworkInvite]) -> int:
    '''
    Check how often a '''
    found = 0
    for value in data:
        invite = NetworkInvite.from_dict(value)
        if invite in network_invites:
            found += 1

    return found


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
