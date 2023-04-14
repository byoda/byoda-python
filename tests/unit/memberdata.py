'''
Test cases for Memberdata class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import sys

import unittest

from byoda.datamodel.memberdata import MemberData

from byoda.util.logger import Logger

TEST_DIR = '/tmp/byoda-tests/kv_sqlite'


class Field:
    def __init__(self, name: str, is_counter: bool):
        self.name = name
        self.is_counter: bool = is_counter


class DataClass:
    def __init__(self, fields: dict):
        self.fields = fields


class TestAccountManager(unittest.TestCase):
    def test_cache_keys(self):
        _LOGGER.debug('test_cache_keys')
        test_data = {'a': 1, 'b': 2, 'c': 3}

        filter_data = DataClass(
            {
                'a': Field('a', True),
                'b': Field('b', True),
                'c': Field('c', True),
                'd': Field('d', False)
            }
        )

        keys = MemberData._get_counter_key_permutations(filter_data, test_data)
        self.assertEqual(
            keys,
            set(
                [
                    'a=1-c=3', 'c=3', 'b=2-c=3', 'b=2', 'a=1',
                    'a=1-b=2', 'a=1-b=2-c=3'
                ]
            )
        )

        counter_filter = {
            'a': 1,
            'b': 2,
        }
        keys = MemberData._get_counter_key_permutations(
            filter_data, counter_filter
        )
        pass


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
