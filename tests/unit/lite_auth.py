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

from byoda import config

from byotubesvr.auth.password import hash_password, verify_password
from byotubesvr.auth.lite_jwt import LiteJWT


class TestAccountManager(unittest.TestCase):
    def test_jwt(self) -> None:
        #
        # Test the python JWT module instead of our code so that we can confirm
        # that any regressions come from our code
        #

        LiteJWT.setup_metrics()

        config.jwt_secrets = ['boink']

        secrets: tuple[str, str, str] = ('test1', 'test2', 'test3')
        encoded: str = LiteJWT.create_auth_token(uuid4(), secrets=secrets)

        self.assertIsNotNone(LiteJWT.verify_auth_token(encoded, secrets))

        # Test with a different secrets
        secrets = ('notest1', 'notest2')
        result: UUID | None = LiteJWT.verify_auth_token(encoded, secrets)
        self.assertIsNone(result)

        # Secrets in different order
        secrets = ('test3', 'test2', 'test1')
        self.assertIsNotNone(LiteJWT.verify_auth_token(encoded, secrets))

    def test_password(self) -> None:
        password = 'test-password'
        hashed_password: str = hash_password(password)

        self.assertTrue(verify_password(password, hashed_password))

        self.assertFalse(verify_password('wrong-password', hashed_password))


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
