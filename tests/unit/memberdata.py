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
    def __init__(self, name: str, fields: dict, referenced_class):
        self.name = name
        self.fields = fields
        self.referenced_class = referenced_class


class TestAccountManager(unittest.TestCase):

    def test_cache_keys(self):
        _LOGGER.debug('test_cache_keys')
        test_data = {'a': 1, 'b': 2, 'c': 3}
        field_data = {
            'a': Field('a', True),
            'b': Field('b', True),
            'c': Field('c', True),
            'd': Field('d', False)
        }
        referenced_class = DataClass(
            'blah', field_data, None
        )

        filter_data = DataClass(
            'gaap', field_data, referenced_class
        )
        keys = MemberData._get_counter_key_permutations(filter_data, test_data)
        self.assertEqual(
            keys,
            set(
                [
                    'gaap',
                    'gaap_a=1',
                    'gaap_a=1_b=2',
                    'gaap_a=1_c=3',
                    'gaap_a=1_b=2_c=3',
                    'gaap_b=2',
                    'gaap_c=3',
                    'gaap_b=2_c=3',
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
        self.assertEqual(
            keys,
            set(
                [
                    'gaap',
                    'gaap_a=1',
                    'gaap_a=1_b=2',
                    'gaap_b=2',
                ]
            )
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
