#!/usr/bin/env python3

'''
Test cases for DataFilter and DataFilterSet classes

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import sys
import unittest

from time import sleep
from uuid import uuid4
from datetime import datetime
from datetime import timezone

from byoda.datamodel.datafilter import DataFilter, DataFilterSet

from byoda.util.logger import Logger


class TestAccountManager(unittest.TestCase):

    def test_string_filter(self):
        filter = DataFilter.create('test', operator='eq', value='just a test')
        self.assertTrue(filter.compare('just a test'))
        self.assertFalse(filter.compare('just another test'))

        filter = DataFilter.create('test', operator='ne', value='just a test')
        self.assertFalse(filter.compare('just a test'))
        self.assertTrue(filter.compare('just another test'))

        filter = DataFilter.create('test', operator='vin', value='just a test')
        self.assertTrue(filter.compare('t a t'))
        self.assertFalse(filter.compare('something'))

        filter = DataFilter.create('test', operator='nin', value='just a test')
        self.assertFalse(filter.compare('t a t'))
        self.assertTrue(filter.compare('something'))

        filter = DataFilter.create(
            'test', operator='regex', value='^j[aou]st'
        )
        self.assertTrue(filter.compare('just a test'))
        self.assertFalse(filter.compare('jest a test'))

        filter = DataFilter.create('test', operator='glob', value='j?st* te')
        self.assertFalse(filter.compare('just a test'))
        self.assertTrue(filter.compare('just a te'))
        self.assertTrue(filter.compare('jest e te'))
        self.assertFalse(filter.compare('not a test'))

    def test_uuid_filter(self):
        val = uuid4()
        filter = DataFilter.create('test', operator='eq', value=val)
        self.assertTrue(filter.compare(val))
        self.assertFalse(filter.compare(uuid4()))

        filter = DataFilter.create('test', operator='ne', value=val)
        self.assertFalse(filter.compare(val))
        self.assertTrue(filter.compare(uuid4()))

    def test_datetime_filter(self):
        before = datetime.now(tz=timezone.utc)
        sleep(1)
        now = datetime.now(tz=timezone.utc)
        sleep(1)
        later = datetime.now(tz=timezone.utc)

        now_seconds = now.timestamp()
        filter = DataFilter.create('test', operator='at', value=now)
        self.assertTrue(filter.compare(now))
        self.assertTrue(filter.compare(now_seconds))
        self.assertFalse(filter.compare(later))

        filter = DataFilter.create('test', operator='nat', value=now)
        self.assertFalse(filter.compare(now))
        self.assertTrue(filter.compare(later))

        filter = DataFilter.create('test', operator='after', value=now)
        self.assertFalse(filter.compare(before))
        self.assertFalse(filter.compare(now))
        self.assertTrue(filter.compare(later))

        filter = DataFilter.create('test', operator='atafter', value=now)
        self.assertFalse(filter.compare(before))
        self.assertTrue(filter.compare(now))
        self.assertTrue(filter.compare(later))

        filter = DataFilter.create('test', operator='before', value=now)
        self.assertTrue(filter.compare(before))
        self.assertFalse(filter.compare(now))
        self.assertFalse(filter.compare(later))

        filter = DataFilter.create('test', operator='atbefore', value=now)
        self.assertTrue(filter.compare(before))
        self.assertTrue(filter.compare(now))
        self.assertFalse(filter.compare(later))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
