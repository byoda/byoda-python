#!/usr/bin/env python3

'''
Test cases for DataFilter and DataFilterSet classes

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023, 2024, 2025
:license    : GPLv3
'''

import sys
import unittest

from time import sleep
from logging import Logger
from uuid import UUID, uuid4
from datetime import datetime
from datetime import timezone

from byoda.datamodel.datafilter import DataFilter

from byoda.util.logger import Logger as ByodaLogger

TEST_STRING: str = 'just a test'


class TestAccountManager(unittest.TestCase):

    def test_string_filter(self) -> None:
        data_filter: DataFilter = DataFilter.create(
            'test', operator='eq', value=TEST_STRING
        )
        self.assertTrue(data_filter.compare(TEST_STRING))
        self.assertFalse(data_filter.compare('just another test'))

        data_filter = DataFilter.create(
            'test', operator='ne', value=TEST_STRING
        )
        self.assertFalse(data_filter.compare(TEST_STRING))
        self.assertTrue(data_filter.compare('just another test'))

        data_filter = DataFilter.create(
            'test', operator='vin', value=TEST_STRING
        )
        self.assertTrue(data_filter.compare('t a t'))
        self.assertFalse(data_filter.compare('something'))

        data_filter = DataFilter.create(
            'test', operator='nin', value=TEST_STRING
        )
        self.assertFalse(data_filter.compare('t a t'))
        self.assertTrue(data_filter.compare('something'))

        data_filter = DataFilter.create(
            'test', operator='regex', value='^j[aou]st'
        )
        self.assertTrue(data_filter.compare(TEST_STRING))
        self.assertFalse(data_filter.compare('jest a test'))

        data_filter = DataFilter.create(
            'test', operator='glob', value='j?st* te'
        )
        self.assertFalse(data_filter.compare(TEST_STRING))
        self.assertTrue(data_filter.compare('just a te'))
        self.assertTrue(data_filter.compare('jest e te'))
        self.assertFalse(data_filter.compare('not a test'))

    def test_uuid_filter(self) -> None:
        val: UUID = uuid4()
        data_filter: DataFilter = DataFilter.create(
            'test', operator='eq', value=val
        )
        self.assertTrue(data_filter.compare(val))
        self.assertFalse(data_filter.compare(uuid4()))

        data_filter = DataFilter.create('test', operator='ne', value=val)
        self.assertFalse(data_filter.compare(val))
        self.assertTrue(data_filter.compare(uuid4()))

    def test_datetime_filter(self) -> None:
        before: datetime = datetime.now(tz=timezone.utc)
        sleep(1)
        now: datetime = datetime.now(tz=timezone.utc)
        sleep(1)
        later: datetime = datetime.now(tz=timezone.utc)

        now_seconds: float = now.timestamp()
        data_filter: DataFilter = DataFilter.create(
            'test', operator='at', value=now
        )
        self.assertTrue(data_filter.compare(now))
        self.assertTrue(data_filter.compare(now_seconds))
        self.assertFalse(data_filter.compare(later))

        data_filter = DataFilter.create('test', operator='nat', value=now)
        self.assertFalse(data_filter.compare(now))
        self.assertTrue(data_filter.compare(later))

        data_filter = DataFilter.create('test', operator='after', value=now)
        self.assertFalse(data_filter.compare(before))
        self.assertFalse(data_filter.compare(now))
        self.assertTrue(data_filter.compare(later))

        data_filter = DataFilter.create('test', operator='atafter', value=now)
        self.assertFalse(data_filter.compare(before))
        self.assertTrue(data_filter.compare(now))
        self.assertTrue(data_filter.compare(later))

        data_filter = DataFilter.create('test', operator='before', value=now)
        self.assertTrue(data_filter.compare(before))
        self.assertFalse(data_filter.compare(now))
        self.assertFalse(data_filter.compare(later))

        data_filter = DataFilter.create('test', operator='atbefore', value=now)
        self.assertTrue(data_filter.compare(before))
        self.assertTrue(data_filter.compare(now))
        self.assertFalse(data_filter.compare(later))


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
