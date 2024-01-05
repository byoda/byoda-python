#!/usr/bin/env python3

'''
Tool to call Data APIs against a pod

This tool does not use the Byoda modules so has no dependency
on the 'byoda-python' repository to be available on the local
file system

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import json
import logging
import asyncio
import argparse

from uuid import UUID
from uuid import uuid4

import httpx

from byoda.datamodel.network import Network

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType

from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.data_wsapi_client import DataWsApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from podserver.util import get_environment_vars

from logging import getLogger

from byoda import config

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import BASE_URL

_LOGGER: Logger = getLogger('')


async def setup_network(test_dir: str | None) -> dict[str, str]:
    if not os.environ.get('ROOT_DIR'):
        os.environ['ROOT_DIR'] = '/tmp/byoda'

    os.environ['PRIVATE_BUCKET'] = 'byoda'
    os.environ['RESTRICTED_BUCKET'] = 'byoda'
    os.environ['PUBLIC_BUCKET'] = 'byoda'
    os.environ['CLOUD'] = 'LOCAL'
    os.environ['NETWORK'] = 'byoda.net'
    os.environ['ACCOUNT_ID'] = str(uuid4())
    os.environ['ACCOUNT_SECRET'] = 'test'
    os.environ['LOGLEVEL'] = 'DEBUG'
    os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
    os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

    data: dict[str, str | int | bool | None] = get_environment_vars()

    config.server = PodServer(bootstrapping=False)

    await config.server.set_document_store(
        DocumentStoreType.OBJECT_STORE, config.server.cloud,
        private_bucket=data['private_bucket'],
        restricted_bucket=data['restricted_bucket'],
        public_bucket=data['public_bucket'],
        root_dir=data['root_dir']
    )

    network: Network = Network(data, data)
    await network.load_network_secrets()

    config.test_case = True

    config.server.network = network

    config.server.paths = network.paths

    return data


async def get_jwt_header(id: UUID | str, base_url: str = BASE_URL,
                         secret: str | None = None, member_token: bool = True
                         ) -> dict[str, str]:

    if not secret:
        secret = os.environ['ACCOUNT_SECRET']

    if member_token:
        service_id: int = ADDRESSBOOK_SERVICE_ID
    else:
        service_id = None

    url: str = base_url + '/v1/pod/authtoken'

    data: dict[str, str] = {
        'username': str(id)[:8],
        'password': secret,
        'service_id': service_id,
        'target_type': IdType.MEMBER.value,
    }

    _LOGGER.debug(f'Calling URL: {url} with data {json.dumps(data)}')
    server: PodServer = config.server
    resp: httpx.Response = httpx.post(url, json=data)
    try:
        result: any = resp.json()
        if resp.status_code != 200:
            await server.shutdown()
            raise PermissionError(f'Failed to get auth token: {result}')
    except json.decoder.JSONDecodeError:
        await server.shutdown()
        raise ValueError(f'Failed to get auth token: {resp.text}')

    _LOGGER.debug(f'JWT acquisition: {resp.status_code} - {resp.text}')
    auth_header: dict[str, str] = {
        'Authorization': f'bearer {result["auth_token"]}'
    }

    return auth_header


async def main(argv: list[str]) -> None:

    await setup_network(None)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--network', '-n', type=str, default=config.DEFAULT_NETWORK
    )
    parser.add_argument(
        '--service_id', '-s', type=str, default=ADDRESSBOOK_SERVICE_ID
    )
    parser.add_argument(
        '--member_id', '-i', type=str, default=os.environ.get('MEMBER_ID')
    )
    parser.add_argument(
        '--password', '-p', type=str,
        default=os.environ.get('ACCOUNT_PASSWORD')
    )
    parser.add_argument('--data-file', '-f', type=str, default='data.json')
    parser.add_argument('--object', '-c', type=str, default='person')
    parser.add_argument(
        '--action', '-a', type=str, default='query',
        choices=[a.value for a in DataRequestType]
    )
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

    args: argparse.Namespace = parser.parse_args(argv[1:])

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

    if not args.member_id and not args.custom_domain:
        raise ValueError('No member id given or set as environment variable')

    if (args.first or args.after) and args.action != 'query':
        raise ValueError(
            'Pagination is only supported for queries, '
            'not mutations or subscriptions'
        )

    network: str = args.network
    service_id: str = args.service_id
    member_id: str = args.member_id
    password: str = args.password
    object_name: str = args.object
    action: str = DataRequestType(args.action)
    depth: str = args.depth
    remote_member_id: str = args.remote_member_id
    custom_domain: str = args.custom_domain
    first: int = args.first
    after: str = args.after

    relations: list[str] | None = None
    if args.relations:
        relations = args.relations.split(',')

    use_proxy: bool
    if not custom_domain:
        # We need to use the proxy because the pod uses an SSL cert signed
        # by the private CA
        use_proxy = True
        base_url: str = f'https://proxy.{network}/{service_id}/{member_id}/api'
    else:
        use_proxy = False
        base_url = f'https://{custom_domain}/api'

    if password:
        auth_header: dict[str, str] | None = await get_jwt_header(
            member_id, base_url=base_url, secret=password,
            member_token=True
        )
    else:
        auth_header = None
        _LOGGER.debug('No password given, making anonymous Data request')

    websockets: bool = False
    if action in (DataRequestType.UPDATES, DataRequestType.COUNTER):
        _LOGGER.debug('Using websockets transport')
        websockets = True

    request_data: dict[str, UUID | str | int | dict[str, str]] = {}
    try:
        with open(args.data_file) as file_desc:
            _LOGGER.debug(f'Loading data from {args.data_file}')
            text = file_desc.read()
            request_data['data'] = json.loads(text)
    except FileNotFoundError:
        if action.value not in ('query', 'delete', 'updates', 'counter'):
            await config.server.shutdown()
            raise

    if remote_member_id:
        request_data['remote_member_id'] = remote_member_id

    if args.filter_field and args.filter_compare and args.filter_value:
        request_data['filter'] = {
            args.filter_field: {args.filter_compare: args.filter_value}
        }
    elif args.filter_field or args.filter_compare or args.filter_value:
        raise ValueError(
            'Filter requires filter_field, filter_compare and '
            'filter_value to be specified'
        )

    if not websockets:
        _LOGGER.debug(
            f'Calling Data API with use_proxy: {use_proxy}, '
            f'custom_domain: {custom_domain}'
        )
        resp: HttpResponse = await DataApiClient.call(
            service_id, object_name, action,
            use_proxy=not bool(custom_domain), custom_domain=custom_domain,
            member_id=member_id, headers=auth_header, data=request_data,
            first=first, after=after, depth=depth, relations=relations,
        )

        try:
            text: dict[str, object] = resp.text
            if action == DataRequestType.QUERY:
                data = resp.json()
                text = json.dumps(data, indent=4)
                print(text)
            else:
                print(f'Result: {text}')
        except httpx.JSONDecodeError as exc:
            _LOGGER.error(f'Failed to parse data: {exc} - {resp.text}')
            raise
    else:
        _LOGGER.debug(
            f'Calling WebSockets Data API {action} with '
            f'auth header: {"Authorization" in auth_header}, '
            f'with use_proxy: {use_proxy}, custom_domain: {custom_domain}'
        )
        async for data in DataWsApiClient.call(
                service_id, object_name, action,
                use_proxy=not bool(custom_domain), custom_domain=custom_domain,
                member_id=member_id, headers=auth_header,
                depth=depth, relations=relations):
            _LOGGER.debug('Received data from the websocket')
            print(data)

    await config.server.shutdown()


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
