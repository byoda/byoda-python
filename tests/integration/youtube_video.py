#!/usr/bin/env python3
'''
Obsolete direct YouTube video metadata scrape integration tests.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2026
:license    : GPLv3
'''

import unittest


@unittest.skip('Direct YouTube metadata scraping was replaced by Scrape.Exchange')
class TestYouTubeVideo(unittest.TestCase):
    def test_direct_scrape_replaced(self) -> None:
        pass


if __name__ == '__main__':
    unittest.main()
