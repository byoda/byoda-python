#!/usr/bin/env python3

'''
Test cases for authentication of REST APIs of BYO.Tube Lite accounts

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import sys
import unittest

from uuid import UUID
from uuid import uuid4

from byoda.util.logger import Logger

from byotubesvr.auth.password import hash_password, verify_password
from byotubesvr.auth.lite_jwt import LiteJWT


class TestAccountManager(unittest.TestCase):
    def test_jwt(self) -> None:
        #
        # Test the python JWT module instead of our code so that we can confirm
        # that any regressions come from our code
        #

        LiteJWT.setup_metrics()

        jwt = LiteJWT(['test1', 'test2', 'test3'])
        encoded: str = jwt.create_auth_token(uuid4())

        self.assertIsNotNone(jwt.verify_access_token(encoded))

        # Test with a different secrets
        jwt_alt = LiteJWT(['notest1', 'notest2'])
        result: UUID | None = jwt_alt.verify_access_token(encoded)
        self.assertIsNone(result)

        # Secrets in different order
        another_jwt = LiteJWT(['test3', 'test2', 'test1'])
        self.assertIsNotNone(another_jwt.verify_access_token(encoded))

    def test_password(self) -> None:
        password = 'test-password'
        hashed_password: str = hash_password(password)

        self.assertTrue(verify_password(password, hashed_password))

        self.assertFalse(verify_password('wrong-password', hashed_password))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
