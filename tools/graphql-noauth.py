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
import logging
import argparse
from uuid import uuid4

from gql import Client, gql
from gql.transport.websockets import WebsocketsTransport
from gql.transport.aiohttp import AIOHTTPTransport


from byoda import config

from byoda.util.logger import Logger


from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID


async def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', '-n', type=str, default='byoda.net')
    parser.add_argument(
        '--service_id', '-s', type=str, default=str(ADDRESSBOOK_SERVICE_ID)
    )
    parser.add_argument(
        '--member_id', '-i', type=str, default=os.environ.get('MEMBER_ID')
    )
    parser.add_argument('--object', '-c', type=str, default='person')
    parser.add_argument('--action', '-a', type=str, default='query')
    parser.add_argument('--depth', '-d', type=int, default=0)
    parser.add_argument('--relations', '-r', type=str, default=None)
    parser.add_argument('--filter-field', type=str, default=None)
    parser.add_argument('--filter-compare', type=str, default=None)
    parser.add_argument('--filter-value', type=str, default=None)
    parser.add_argument('--remote-member-id', '-m', type=str, default=None)
    parser.add_argument('--first', type=int, default=None)
    parser.add_argument('--after', type=str, default=None)
    parser.add_argument(
        '--custom-domain', '-u', type=str,
        default=os.environ.get('CUSTOM_DOMAIN')
    )
    parser.add_argument(
        '--debug', default=False, action='store_true'
    )

    args = parser.parse_args(argv[1:])

    if not args.member_id:
        raise ValueError('No member id given or set as environment variable')

    global _LOGGER
    if args.debug:
        _LOGGER = Logger.getLogger(
            sys.argv[0], debug=True, verbose=False, json_out=False,
            loglevel=logging.DEBUG
        )
    else:
        _LOGGER = Logger.getLogger(
            sys.argv[0], debug=False, verbose=False, json_out=False,
            loglevel=logging.WARNING
        )

    network: str = args.network
    service_id: str = args.service_id
    member_id: str = args.member_id
    object_name: str = args.object
    action: str = args.action
    depth: str = args.depth
    remote_member_id: str = args.remote_member_id
    custom_domain: str = args.custom_domain
    first: int = args.first
    after: str = args.after

    relations = None
    if args.relations:
        relations = args.relations.split(',')

    if args.object not in GRAPHQL_STATEMENTS:
        await config.server.shutdown()
        raise ValueError(
            f'{args.object} not in list of available objects for the service: '
            ', '.join(GRAPHQL_STATEMENTS.keys())
        )

    if not custom_domain:
        # We need to use the proxy because the pod uses an SSL cert signed
        # by the private CA
        base_url: str = f'https://proxy.{network}/{service_id}/{member_id}/api'
        ws_base_url: str = \
            f'wss://proxy.{network}/{service_id}/{member_id}/ws-api'
    else:
        base_url: str = f'https://{custom_domain}/api'
        ws_base_url: str = f'wss://{custom_domain}/ws-api'

    graphql_url = f'{base_url}/v1/data/service-{service_id}'

    _LOGGER.debug(f'Using GraphQL URL: {graphql_url}')

    vars = {'query_id': uuid4()}

    vars['depth'] = depth
    if relations:
        vars['relations'] = relations

    vars['first'] = first
    vars['after'] = after

    if remote_member_id:
        vars['remote_member_id'] = remote_member_id

    if args.filter_field and args.filter_compare and args.filter_value:
        vars['filters'] = {
            args.filter_field: {args.filter_compare: args.filter_value}
        }
    elif args.filter_field or args.filter_compare or args.filter_value:
        raise ValueError(
            'Filter requires filter_field, filter_compare and '
            'filter_value to be specified'
        )

    if action == 'query':
        await call_http(graphql_url, object_name, 'query', vars)
    else:
        raise ValueError(
            f'Only queries are supported at this time, not {action}'
        )


async def call_http(graphql_url: str, object_name: str, vars: dict) -> None:
    _LOGGER.debug(f'Calling URL {graphql_url}')
    transport = AIOHTTPTransport(url=graphql_url)
    async with Client(transport=transport,
                      fetch_schema_from_transport=False) as session:

        try:
            response = await session.execute(
                GRAPHQL_STATEMENTS[object_name]['query'], variable_values=vars
            )
            print('Data returned by GraphQL: ')
            print(response)
        except (ValueError) as exc:
            _LOGGER.error(
                f'Failed to parse response: {exc}: {await response.text()}'
            )
        raise


async def call_websocket(graphql_url: str, object_name: str, action: str
                         ) -> None:
    _LOGGER.debug(f'Calling URL {graphql_url}')
    transport = WebsocketsTransport(
        url=graphql_url,
        subprotocols=[WebsocketsTransport.GRAPHQLWS_SUBPROTOCOL]
    )

    async with Client(
        transport=transport, fetch_schema_from_transport=False,
        execute_timeout=600
    ) as session:
        request = GRAPHQL_STATEMENTS[object_name][action]
        while True:
            message = gql(request)
            result = await session.execute(message)
            print(
                orjson.dumps(
                    result, option=orjson.OPT_INDENT_2
                ).decode('utf-8')
            )


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
