#!/usr/bin/env python3

'''
Test cases for json schema

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import sys
import json
import unittest
import logging

import fastjsonschema

from byoda.util import Logger

from byoda.datamodel import MemberData, Schema

from byoda.storage import FileStorage


_LOGGER = logging.getLogger(__name__)

DEFAULT_SCHEMA = 'services/default.json'

data = {
    'given_name': 'Steven',
    'family_name': 'Hessing',
}


class TestAccountManager(unittest.TestCase):
    def test_jsonschema(self):
        with open(DEFAULT_SCHEMA) as fd:
            fastjson_schema = json.load(fd)

        validate = fastjsonschema.compile(fastjson_schema)

        test = validate(data)
        self.assertEqual(data, test)

        storage_driver = FileStorage('.')
        schema = Schema(DEFAULT_SCHEMA)
        obj = MemberData(
            schema, storage_driver
        )
        obj.load_from_file('tests/collateral/memberdata.json')

        schema.generate_graphql_schema()

        result = schema.gql_schema.execute(
            '{ givenName }'
        )
        self.assertEqual(result.data['givenName'], 'givenName stranger')


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
