#!/usr/bin/env python3

'''
Creates secrets for a service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import sys
import os
import asyncio
import shutil
import argparse

from uuid import uuid4
from logging import Logger

import httpx

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service

from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.server import Server

from byoda.secrets.networkrootca_secret import NetworkRootCaSecret

from byoda.servers.pod_server import PodServer

from podserver.util import get_environment_vars

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

_LOGGER: Logger | None = None

_ROOT_DIR: str = os.environ['HOME'] + '/.byoda'


async def main(argv) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument('--schema', '-s', type=str)
    parser.add_argument('--network', '-n', type=str, default='test')
    parser.add_argument('--root-directory', '-r', type=str, default=_ROOT_DIR)
    parser.add_argument('--password', '-p', type=str, default='byoda')
    parser.add_argument(
        '--local', default=True, action='store_false'
    )
    args: argparse.Namespace = parser.parse_args()

    if not os.environ.get('ROOT_DIR'):
        os.environ['ROOT_DIR'] = args.root_directory

    os.environ['PRIVATE_BUCKET'] = 'byoda'
    os.environ['RESTRICTED_BUCKET'] = 'byoda'
    os.environ['PUBLIC_BUCKET'] = 'byoda'
    os.environ['CLOUD'] = 'LOCAL'
    os.environ['NETWORK'] = args.network
    os.environ['ACCOUNT_ID'] = str(uuid4())
    os.environ['ACCOUNT_USERNAME'] = 'dummy'
    os.environ['ACCOUNT_SECRET'] = 'test'
    os.environ['LOGLEVEL'] = 'DEBUG'
    os.environ['PRIVATE_KEY_SECRET'] = args.password
    os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

    network_data: dict[str, str | int | bool | None] = get_environment_vars()

    global _LOGGER
    _LOGGER = ByodaLogger.getLogger(
        argv[0], debug=args.debug, verbose=args.verbose,
        json_out=False
    )

    root_dir: str = args.root_directory

    if root_dir.startswith('/tmp') and os.path.exists(root_dir):
        _LOGGER.debug(f'Wiping temporary root directory: {root_dir}')
        shutil.rmtree(root_dir)

    network_dir: str = f'{root_dir}/network-{args.network}'
    network_cert_filepath: str = (
        network_dir + f'/network-{args.network}-root-ca-cert.pem'
    )

    if not os.path.exists(network_cert_filepath):
        os.makedirs(network_dir, exist_ok=True)
        url: str = f'https://dir.{args.network}/root-ca.pem'
        resp: httpx.Response = httpx.get(url)
        with open(network_cert_filepath, 'w') as file_desc:
            file_desc.write(resp.text)

    config.server = PodServer(
        bootstrapping=False,
        db_connection_string=network_data.get('db_connection')
    )

    await config.server.set_document_store(
        DocumentStoreType.OBJECT_STORE, config.server.cloud,
        private_bucket=network_data['private_bucket'],
        restricted_bucket=network_data['restricted_bucket'],
        public_bucket=network_data['public_bucket'],
        root_dir=network_data['root_dir']
    )

    network: Network = await load_network(args, network_data)

    service = Service(network=network)
    if args.schema:
        await service.examine_servicecontract(args.schema)

    _LOGGER.debug(f'Creating secrets for service ID {service.service_id}')
    await service.create_secrets(
        network.services_ca, password=args.password
    )


async def load_network(args: argparse.ArgumentParser,
                       network_data: dict[str, str]) -> Network:
    '''
    Load existing network secrets

    :raises: ValueError, NotImplementedError
    '''

    network = Network(network_data, network_data)
    await network.load_network_secrets()

    config.server = Server(network)

    if not await network.paths.network_directory_exists():
        raise ValueError(f'Network {args.network} not found')

    network.root_ca = NetworkRootCaSecret(network.paths)

    await network.root_ca.load(with_private_key=False)

    return network


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
