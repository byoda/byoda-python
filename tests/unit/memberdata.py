'''
Test cases for Memberdata class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import sys
import unittest

from logging import Logger

from byoda.datamodel.memberdata import MemberData

from byoda.util.logger import Logger as ByodaLogger


TEST_DIR = '/tmp/byoda-tests/kv_sqlite'


class Field:
    def __init__(self, name: str, is_counter: bool):
        self.name = name
        self.is_counter: bool = is_counter


class DataClass:
    def __init__(self, name: str, fields: dict, referenced_class):
        self.name: str = name
        self.fields = fields
        self.referenced_class: any = referenced_class


class TestAccountManager(unittest.TestCase):

    def test_cache_keys(self) -> None:
        _LOGGER.debug('test_cache_keys')
        test_data: dict[str, int] = {'a': 1, 'b': 2, 'c': 3}
        field_data: dict[str, Field] = {
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
        keys: set[str] = MemberData._get_counter_key_permutations(
            filter_data, test_data
        )
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

        counter_filter: dict[str, int] = {
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
    _LOGGER: Logger = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
