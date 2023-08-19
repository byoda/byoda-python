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
import asyncio
import logging
import argparse

from uuid import UUID

import yaml
import orjson

from byoda.datamodel.network import Network
from byoda.datamodel.claim import Claim
from byoda.datamodel.app import App

from byoda.datastore.document_store import DocumentStoreType

from byoda.datatypes import CloudType
from byoda.datatypes import IdType
from byoda.datatypes import ClaimStatus

from byoda.servers.app_server import AppServer

from byoda import config

from byoda.util.logger import Logger

_LOGGER = None

DEFAULT_NETWORK: str = "byoda.net"
DEFAULT_SERVICE_ID: str = "4294929430"
DEFAULT_TEST_DIRECTORY = '/tmp/byoda'


async def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', default=False, action='store_true')
    parser.add_argument('--config-file', '-c', type=str, default='config.yml')
    parser.add_argument(
        '--password', '-p', type=str,
        default=os.environ.get('BYODA_PASSWORD', 'byoda')
    )
    parser.add_argument('files', nargs=argparse.REMAINDER)

    args = parser.parse_args(argv[1:])

    global _LOGGER
    if args.debug:
        _LOGGER = Logger.getLogger(
            sys.argv[0], debug=True, json_out=False, loglevel=logging.DEBUG
        )
    else:
        _LOGGER = Logger.getLogger(
            sys.argv[0], json_out=False, loglevel=logging.WARNING
        )

    with open(args.config_file) as file_desc:
        app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    network = Network(
        app_config['appserver'], app_config['application']
    )
    fqdn: str = app_config['appserver']['fqdn']

    server = AppServer(app_config['appserver']['app_id'], network, app_config)

    await server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType.LOCAL,
        private_bucket='byoda',
        restricted_bucket='byoda',
        public_bucket='byoda',
        root_dir=app_config['appserver']['root_dir']
    )

    config.server = server

    await network.load_network_secrets()

    await server.load_secrets(
        password=app_config['appserver']['private_key_password']
    )

    files: list[str] = args.files
    confirmation_needed: bool = False
    request_dir: str = server.get_claim_filepath(ClaimStatus.PENDING)
    if not files:
        files = os.listdir(request_dir)
        # We sort by newest files first so we will look at the newest
        # request when there are multiple requests for the same asset
        files.sort(
            key=lambda x: os.path.getmtime(f'{request_dir}/{x}'),
            reverse=True
        )
        confirmation_needed = True

    for filename in files:
        request_file = request_dir + filename
        with open(request_file, 'rb') as file_desc:
            raw_data = file_desc.read()
            data = orjson.loads(raw_data)

        claim_data = data['claim_data']
        accepted_file = server.get_claim_filepath(
            ClaimStatus.ACCEPTED, claim_data['asset_id']
        )
        if is_duplicate_asset(request_file, accepted_file, data['requester_id']):
            continue

        if confirmation_needed:
            print()
            print(raw_data.decode('utf-8'))
            print()
            confirmation = input('Sign this claim (Y(es)/R(eject)/S(kip))? ')
            if confirmation.lower() in ('s', 'skip'):
                print(
                    f'Skipping claim: {data["request_id"]} in {request_file}'
                )
                continue
            elif confirmation.lower() in ('r', 'reject'):
                print(
                    f'Rejecting claim: {data["request_id"]} in {request_file}'
                )
                data['status'] = 'rejected'
                rejected_file = server.get_claim_filepath(
                    ClaimStatus.REJECTED, data['request_id']
                )
                with open(rejected_file, 'wb') as file_desc:
                    file_desc.write(
                        orjson.dumps(
                            data,
                            option=orjson.OPT_SORT_KEYS |
                            orjson.OPT_INDENT_2
                        )
                    )
                os.remove(request_file)
                continue

        claim = Claim.build(
            data['claims'], app_config['appserver']['fqdn'], IdType.APP,
            claim_data['asset_type'], 'asset_id', claim_data['asset_id'],
            sorted(claim_data.keys()),
            data['requester_id'], IdType(data['requester_type']),
            f'https://{fqdn}/signature', f'https://{fqdn}/renewal',
            f'https://{fqdn}/confirmation'
        )

        app: App = server.app
        claim.create_signature(claim_data, app.data_secret)
        signed_claim_data: dict = claim.as_dict()
        signed_claim_data['claim_data'] = claim_data

        with open(accepted_file, 'w') as file_desc:
            file_desc.write(
                orjson.dumps(
                    signed_claim_data,
                    option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2
                ).decode('utf-8')
            )

        os.remove(request_file)


def is_duplicate_asset(in_file: str, out_file: str, requester_id: UUID):
    if os.path.exists(out_file):
        if os.stat(in_file).st_mtime < os.stat(out_file).st_mtime:
            _LOGGER.debug(
                f'Skipping claim request {in_file} as it is older than '
                f'the claim file {out_file}'
            )
            return True

        with open(out_file, 'rb') as file_desc:
            data = orjson.loads(file_desc.read())
            if 'requester_id' not in data:
                _LOGGER.warning('Invalid claim file: %s', out_file)
                return True
            if str(requester_id) != data['requester_id']:
                _LOGGER.warning(
                    f'Requester ID requester_id does not match requester_id of '
                    f'existing claim: {data["requester_id"]}'
                )
                return True
    return False


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
