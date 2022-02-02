#!/usr/bin/env python3

'''
Test the MemberDB

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import os
import sys
import yaml
import shutil
import unittest
from uuid import UUID

from byoda.datatypes import MemberStatus

from byoda.util.logger import Logger

from byoda.datamodel.network import Network

from byoda.servers.service_server import ServiceServer

from byoda import config

CONFIG_FILE = 'tests/collateral/config.yml'

TEST_MEMBER_UUID = UUID('aaaaaaaa-ab12-2612-6212-30808f40d0fd')


class TestKVCache(unittest.TestCase):
    PROCESS = None
    APP_CONFIG = None

    @classmethod
    def setUpClass(cls):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        with open(CONFIG_FILE) as file_desc:
            cls.APP_CONFIG = yaml.load(file_desc, Loader=yaml.SafeLoader)

        test_dir = cls.APP_CONFIG['svcserver']['root_dir']
        try:
            shutil.rmtree(test_dir)
        except FileNotFoundError:
            pass

        os.makedirs(test_dir)

        # Create the network so that the constructor of ServiceServer
        # can load it.
        Network.create(
            cls.APP_CONFIG['application']['network'],
            cls.APP_CONFIG['svcserver']['root_dir'],
            cls.APP_CONFIG['svcserver']['private_key_password']
        )

        config.server = ServiceServer(cls.APP_CONFIG)

        member_db = config.server.member_db
        member_db.service_id = cls.APP_CONFIG['svcserver']['service_id']
        member_db.delete_meta(TEST_MEMBER_UUID)
        member_db.delete_members_list()

    @classmethod
    def tearDownClass(cls):
        pass

    def test_memberdb_ops(self):
        member_db = config.server.member_db

        with self.assertRaises(ValueError):
            member_db.service_id = 'Fails as cache keys have already been used'

        self.assertFalse(member_db.exists(TEST_MEMBER_UUID))

        data = {
            'member_id': TEST_MEMBER_UUID,
            'remote_addr': '127.0.0.1',
            'schema_version': 1,
            'data_secret': 'blah',
            'status': MemberStatus.REGISTERED,
        }

        member_db.add_meta(
            data['member_id'], data['remote_addr'], data['schema_version'],
            data['data_secret'], data['status']
        )

        value = member_db.get_meta(TEST_MEMBER_UUID)

        for key in data.keys():
            self.assertTrue(data[key], value[key])

        data = {
            'member_id': TEST_MEMBER_UUID,
            'remote_addr': '10.10.10.10',
            'schema_version': 5,
            'data_secret': 'blahblah',
            'status': MemberStatus.SIGNED,
        }

        member_db.add_meta(
            data['member_id'], data['remote_addr'], data['schema_version'],
            data['data_secret'], data['status']
        )

        value = member_db.get_meta(TEST_MEMBER_UUID)

        for key in data.keys():
            self.assertTrue(data[key], value[key])

        data = {
            'member_id': str(TEST_MEMBER_UUID),
            'remote_addr': '10.10.10.10',
            'schema_version': 5,
            'data_secret': 'blahblah',
            'status': MemberStatus.SIGNED.value,
        }

        member_db.set_data(TEST_MEMBER_UUID, data)

        self.assertEqual(member_db.get_data(TEST_MEMBER_UUID), data)

        self.assertEqual(member_db.pos(TEST_MEMBER_UUID), 0)

        self.assertEqual(member_db.get_next(), TEST_MEMBER_UUID)

        self.assertEqual(member_db.get_next(timeout=1), None)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
