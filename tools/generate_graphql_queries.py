#!/usr/bin/env python3

'''
Tool to generate GraphQL queries for a schema.


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import orjson
import argparse

import jinja2

from byoda.datamodel.schema import Schema
from byoda.datamodel.dataclass import DataType


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--schema', '-s', type=str,
        default='tests/collateral/addressbook.json'
    )
    parser.add_argument('--language', '-l', type=str, default='python')
    parser.add_argument(
        '--out', '-o', type=str, default='tests/lib/addressbook_queries.py'
    )
    args = parser.parse_args()

    with open(args.schema) as file_desc:
        text = file_desc.read()

    data = orjson.loads(text)

    schema = Schema(data)
    schema.load(verify_contract_signatures=False)
    schema.get_graphql_classes()
    loader = jinja2.FileSystemLoader('podserver/files')
    environment = jinja2.Environment(
        loader=loader,
        extensions=[
            'jinja2.ext.do',
            'jinja2.ext.loopcontrols',
            'jinja2_strcase.StrcaseExtension'],
        trim_blocks=True,
        autoescape=True
    )
    template = environment.get_template('graphql_queries.jinja')

    code = template.render(
        classes=schema.data_classes,
        DataType=DataType
    )

    with open(args.out, 'w') as file_desc:
        file_desc.write(code)


if __name__ == '__main__':
    main(sys.argv)
