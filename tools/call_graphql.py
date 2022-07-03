#!/usr/bin/env python3

'''
Tool to call GraphQL APIs against a pod

This tool does not use the Byoda modules so has no dependency
on the 'byoda-python' repository to be available on the local
file system

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import sys
import orjson
import asyncio
import argparse

from byoda.util.api_client.graphql_client import GraphQlClient

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS
from tests.lib.auth import get_jwt_header
from tests.lib.setup import setup_network


async def main(argv):
    await setup_network(None)
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', '-n', type=str, default='byoda.net')
    parser.add_argument('--service_id', '-s', type=str, default='4294929430')
    parser.add_argument(
        '--member_id', '-m', type=str, default=os.environ['MEMBER_ID']
    )
    parser.add_argument('--password', '-p', type=str, default='byoda')
    parser.add_argument('--data-file', '-f', type=str, default='data.json')
    parser.add_argument('--class_name', '-c', type=str, default='person')
    parser.add_argument('--action', '-a', type=str, default='query')
    args = parser.parse_args()

    network = args.network
    service_id = args.service_id
    member_id = args.member_id
    password = args.password
    class_name = args.class_name
    action = args.action

    member_id = '86c8c2f0-572e-4f58-a478-4037d2c9b94a'
    password = 'supersecret'

    if args.class_name not in GRAPHQL_STATEMENTS:
        raise ValueError(
            f'{args.class_name} not in available classes: ' +
            ', '.join(GRAPHQL_STATEMENTS.keys())
        )

    if args.action not in GRAPHQL_STATEMENTS[args.class_name]:
        raise ValueError(
            f'{args.action} not in list of available actions for class '
            f'{args.class_name}: ' +
            ", ".join(GRAPHQL_STATEMENTS[args.class_name])
        )

    vars = {}
    try:
        with open(args.data_file) as file_desc:
            text = file_desc.read()
            vars = orjson.loads(text)
    except FileNotFoundError:
        if action != 'query':
            raise

    base_url = f'https://proxy.{network}/{service_id}/{member_id}/api'

    auth_header = get_jwt_header(
        base_url=base_url, id=member_id, secret=password,
        member_token=True
    )

    graphql_url = f'{base_url}/v1/data/service-{service_id}'

    response = await GraphQlClient.call(
        graphql_url, GRAPHQL_STATEMENTS[class_name][action],
        vars=vars, timeout=10, headers=auth_header
    )
    result = await response.json()

    data = result.get('data')
    if data:
        text = orjson.dumps(data, option=orjson.OPT_INDENT_2)
        print('Data returned by GraphQL: ')
        print(text.decode('utf-8'))
    else:
        print(f'GraphQL error: {result.get("errors")}')


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
