#!/usr/bin/env python3

'''
Creates secrets for a service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import sys
import os
import argparse
import shutil

import requests

from byoda.util import Logger

from byoda.datamodel import Network
from byoda.datamodel import Service
from byoda.datamodel import Server

from byoda.secrets import NetworkRootCaSecret

from byoda import config

_LOGGER = None

_ROOT_DIR = os.environ['HOME'] + '/.byoda'


def main(argv):
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
    args = parser.parse_args()

    # Network constructor expects parameters to be in a dict
    network_data = {
        'private_key_password': args.password,
        'cloud': 'LOCAL',
        'bucket_prefix': None,
        'roles': [],
        'network': args.network,
        'root_dir': args.root_directory,
    }

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], debug=args.debug, verbose=args.verbose,
        json_out=False
    )

    root_dir = args.root_directory

    if root_dir.startswith('/tmp') and os.path.exists(root_dir):
        _LOGGER.debug(f'Wiping temporary root directory: {root_dir}')
        shutil.rmtree(root_dir)

    network_dir = f'{root_dir}/network-{args.network}'
    network_cert_filepath = (
        network_dir + f'/network-{args.network}-root-ca-cert.pem'
    )

    if not os.path.exists(network_cert_filepath):
        os.makedirs(network_dir, exist_ok=True)
        resp = requests.get(f'https://dir.{args.network}/root-ca.pem')
        with open(network_cert_filepath, 'w') as file_desc:
            file_desc.write(resp.text)

    network = load_network(args, network_data)

    service = Service(network=network, filepath=args.schema)
    service.create_secrets(
        network.services_ca, password=args.password, local=False
    )


def load_network(args: argparse.ArgumentParser, network_data: dict[str, str]
                 ) -> Network:
    '''
    Load existing network secrets

    :raises: ValueError, NotImplementedError
    '''

    network = Network(network_data, network_data)

    config.server = Server()
    config.server.network = network

    if not network.paths.network_directory_exists():
        raise ValueError(f'Network {args.network} not found')

    network.root_ca = NetworkRootCaSecret(network.paths)

    network.root_ca.load(with_private_key=False)

    return network


if __name__ == '__main__':
    main(sys.argv)
