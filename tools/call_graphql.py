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
import json
import orjson
import asyncio
import logging
import argparse
from uuid import UUID, uuid4

import requests

from byoda.util.api_client.graphql_client import GraphQlClient

from byoda import config

from byoda.util.logger import Logger

from byoda.datatypes import CloudType

from byoda.datamodel.network import Network

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.servers.pod_server import PodServer

from podserver.util import get_environment_vars

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS
from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID


async def setup_network(test_dir: str) -> dict[str, str]:
    if not os.environ.get('ROOT_DIR'):
        os.environ['ROOT_DIR'] = '/byoda'

    os.environ['BUCKET_PREFIX'] = 'byoda'
    os.environ['CLOUD'] = 'LOCAL'
    os.environ['NETWORK'] = 'byoda.net'
    os.environ['ACCOUNT_ID'] = str(uuid4())
    os.environ['ACCOUNT_SECRET'] = 'test'
    os.environ['LOGLEVEL'] = 'DEBUG'
    os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
    os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

    network_data = get_environment_vars()

    network = Network(network_data, network_data)
    await network.load_network_secrets()

    config.test_case = True

    config.server = PodServer(network)
    config.server.network = network

    await config.server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType(network_data['cloud']),
        bucket_prefix=network_data['bucket_prefix'],
        root_dir=network_data['root_dir']
    )

    config.server.paths = network.paths

    await config.server.set_data_store(DataStoreType.SQLITE)

    return network_data


async def get_jwt_header(id: UUID, base_url: str = BASE_URL,
                         secret: str = None, member_token: bool = True):

    if not secret:
        secret = os.environ['ACCOUNT_SECRET']

    if member_token:
        service_id = ADDRESSBOOK_SERVICE_ID
    else:
        service_id = None

    url = base_url + '/v1/pod/authtoken'

    data = {
        'username': str(id)[:8],
        'password': secret,
        'service_id': service_id,
    }
    _LOGGER.debug(f'Calling URL: {url} with data {json.dumps(data)}')
    response = requests.post(url, json=data)
    try:
        result = response.json()
        if response.status_code != 200:
            await config.server.shutdown()
            raise PermissionError(f'Failed to get auth token: {result}')
    except json.decoder.JSONDecodeError:
        await config.server.shutdown()
        raise ValueError(f'Failed to get auth token: {response.text}')

    _LOGGER.debug(f'JWT acquisition: {response.status_code} - {response.text}')
    auth_header = {
        'Authorization': f'bearer {result["auth_token"]}'
    }

    return auth_header


async def main(argv):

    await setup_network(None)
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', '-n', type=str, default='byoda.net')
    parser.add_argument('--service_id', '-s', type=str, default='4294929430')
    parser.add_argument(
        '--member_id', '-i', type=str, default=os.environ.get('MEMBER_ID')
    )
    parser.add_argument(
        '--password', '-p', type=str,
        default=os.environ.get('ACCOUNT_PASSWORD')
    )
    parser.add_argument('--data-file', '-f', type=str, default='data.json')
    parser.add_argument('--object', '-c', type=str, default='person')
    parser.add_argument('--action', '-a', type=str, default='query')
    parser.add_argument('--depth', '-d', type=int, default=0)
    parser.add_argument('--relations', '-r', type=str, default=None)
    parser.add_argument('--filter-field', type=str, default=None)
    parser.add_argument('--filter-compare', type=str, default=None)
    parser.add_argument('--filter-value', type=str, default=None)
    parser.add_argument('--remote-member-id', '-m', type=str, default=None)
    parser.add_argument(
        '--debug', default=False, action='store_true'
    )

    args = parser.parse_args(argv[1:])

    if not args.member_id:
        raise ValueError('No member id given')

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

    network = args.network
    service_id = args.service_id
    member_id = args.member_id
    password = args.password
    object = args.object
    action = args.action
    depth = args.depth
    remote_member_id = args.remote_member_id

    relations = None
    if args.relations:
        relations = args.relations.split(',')

    if args.object not in GRAPHQL_STATEMENTS:
        await config.server.shutdown()
        raise ValueError(
            f'{args.object} not in list of available objects for the service: '
            ', '.join(GRAPHQL_STATEMENTS.keys())
        )

    if args.action not in GRAPHQL_STATEMENTS[args.object]:
        await config.server.shutdown()
        raise ValueError(
            f'{args.action} not in list of available actions for object '
            f'{args.object}: ' +
            ", ".join(GRAPHQL_STATEMENTS[args.object])
        )

    base_url = f'https://proxy.{network}/{service_id}/{member_id}/api'

    auth_header = await get_jwt_header(
        member_id, base_url=base_url, secret=password,
        member_token=True
    )

    graphql_url = f'{base_url}/v1/data/service-{service_id}'
    _LOGGER.debug(f'Using GraphQL URL: {graphql_url}')

    vars = {'query_id': uuid4()}
    try:
        with open(args.data_file) as file_desc:
            _LOGGER.debug(f'Loading data from {args.data_file}')
            text = file_desc.read()
            vars = orjson.loads(text)
    except FileNotFoundError:
        if action not in ('query', 'delete'):
            await config.server.shutdown()
            raise

    if action in ('query', 'append'):
        vars['depth'] = depth
        if relations:
            vars['relations'] = relations

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

    response = await GraphQlClient.call(
        graphql_url, GRAPHQL_STATEMENTS[object][action],
        vars=vars, headers=auth_header, timeout=30
    )
    try:
        result = await response.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        await config.server.shutdown()
        _LOGGER.error(
            f'Failed to parse response: {exc}: {await response.text()}'
        )
        raise

    data = result.get('data')
    if data:
        try:
            text = orjson.dumps(data, option=orjson.OPT_INDENT_2)
            print('Data returned by GraphQL: ')
            print(text.decode('utf-8'))
        except Exception as exc:
            _LOGGER.error(f'Failed to parse data: {exc} - {data}')
            raise
    else:
        print(f'GraphQL error: {result.get("errors")}')

    await config.server.shutdown()

if __name__ == '__main__':
    asyncio.run(main(sys.argv))
