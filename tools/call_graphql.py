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
import shutil
import asyncio
import argparse
from uuid import UUID, uuid4
from typing import Dict

import requests
from requests.auth import HTTPBasicAuth

from byoda.util.api_client.graphql_client import GraphQlClient

from byoda import config

from byoda.datatypes import CloudType

from byoda.datamodel.network import Network

from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.pod_server import PodServer

from podserver.util import get_environment_vars

from tests.lib.addressbook_queries import GRAPHQL_STATEMENTS
from tests.lib.defines import BASE_URL
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID


async def setup_network(test_dir: str) -> Dict[str, str]:
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

    return network_data


def get_jwt_header(base_url: str = BASE_URL, id: UUID = None,
                   secret: str = None, member_token: bool = True):

    if not id:
        account = config.server.account
        id = account.account_id

    if not secret:
        secret = os.environ['ACCOUNT_SECRET']

    if member_token:
        service_id = ADDRESSBOOK_SERVICE_ID
        url = base_url + f'/v1/pod/authtoken/service_id/{service_id}'
    else:
        url = base_url + '/v1/pod/authtoken'

    response = requests.get(
        url, auth=HTTPBasicAuth(str(id)[:8], secret)
    )
    result = response.json()
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
        '--member_id', '-i', type=str, default=os.environ['MEMBER_ID']
    )
    parser.add_argument(
        '--password', '-p', type=str, default=os.environ['ACCOUNT_PASSWORD']
    )
    parser.add_argument('--data-file', '-f', type=str, default='data.json')
    parser.add_argument('--class-name', '-c', type=str, default='person')
    parser.add_argument('--action', '-a', type=str, default='query')
    parser.add_argument('--depth', '-d', type=int, default=0)
    parser.add_argument('--relations', '-r', type=str, default=None)
    parser.add_argument('--filter-field', type=str, default=None)
    parser.add_argument('--filter-compare', type=str, default=None)
    parser.add_argument('--filter-value', type=str, default=None)
    parser.add_argument('--remote-member-id', '-m', type=str, default=None)

    args = parser.parse_args()

    network = args.network
    service_id = args.service_id
    member_id = args.member_id
    password = args.password
    class_name = args.class_name
    action = args.action
    depth = args.depth
    remote_member_id = args.remote_member_id

    relations = None
    if args.relations:
        relations = args.relation.split(',')

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

    base_url = f'https://proxy.{network}/{service_id}/{member_id}/api'

    auth_header = get_jwt_header(
        base_url=base_url, id=member_id, secret=password,
        member_token=True
    )

    graphql_url = f'{base_url}/v1/data/service-{service_id}'

    vars = {}
    try:
        with open(args.data_file) as file_desc:
            text = file_desc.read()
            vars = orjson.loads(text)
    except FileNotFoundError:
        if action != 'query':
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
