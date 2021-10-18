#!/usr/bin/env python3

'''
Manages the signing of a data contract of a service.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import argparse
import sys
import json

import requests

from byoda.datamodel import Network, Service
from byoda.datamodel import NETWORK_SERVICE_API
from byoda.storage.filestorage import FileStorage

from byoda.util import SignatureType
from byoda.util import Logger
from byoda.util.secrets.service_secret import ServiceSecret

_LOGGER = None

_ROOT_DIR = os.environ['HOME'] + '/.byoda'


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument(
        '--signing-party', '-s', type=str, default=SignatureType.SERVICE.value,
        choices=[i.value for i in SignatureType]
    )
    parser.add_argument('--contract', '-c', type=str)
    parser.add_argument('--root-directory', '-r', type=str, default=_ROOT_DIR)
    parser.add_argument('--network', type=str, default='byoda.net')
    parser.add_argument('--password', '-p', type=str, default='byoda')
    parser.add_argument(
        '--local', default=False, action='store_true'
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

    network = load_network(args, network_data)
    service = load_service(args, network)
    schema = service.schema.json_schema

    if 'signatures' not in schema:
        schema['signatures'] = {}

    if args.signing_party == SignatureType.NETWORK.value:
        if schema['signatures'].get(SignatureType.NETWORK.value):
            raise ValueError('Schema has already been signed by the network')

        if SignatureType.SERVICE.value not in schema['signatures']:
            raise ValueError('Schema has not been signed by the service')

        # We first verify the service signature before we add the network
        # signature
        service.schema.verify_signature(
            service.data_secret, SignatureType.SERVICE
        )

        if args.local:
            service.schema.create_signature(
                network.data_secret, SignatureType.NETWORK
            )
        else:
            service_secret = ServiceSecret(None, service.service_id, network)
            service_secret.load(with_private_key=True)
            key_path = service_secret.save_tmp_private_key()
            url = NETWORK_SERVICE_API.format(network=args.network)
            response = requests.patch(
                url, cert=(service_secret.cert_file, key_path)
            )
            if response.status_code == 200:
                data = response.json()
                if data['errors']:
                    _LOGGER.debug('Validation of service by the network failed')
                    for error in data['errors']:
                        _LOGGER.debug(f'Validation error: {error}')
                else:
                    response = requests.get(
                        f'{url}/service_id={service.service_id}'
                    )
                    if response.status_code == 200:
                        with open(args.contract, 'w') as file_desc:
                            file_desc.write(response.text)
                        _LOGGER.debug('Network validation')
    else:
        if schema['signatures'].get(SignatureType.NETWORK.value):
            raise ValueError('Schema has already been signed by the network')

        if SignatureType.SERVICE.value in schema['signatures']:
            raise ValueError('Schema has already been signed by the service')

        service.schema.create_signature(
            service.data_secret, SignatureType.SERVICE
        )

    if not args.root_directory.startswith('/'):
        # Hack to make relative paths work with the FileStorage class
        args.root_directory = os.getcwd()

    storage_driver = FileStorage(args.root_directory)
    service.schema.save(args.contract, storage_driver=storage_driver)


def load_network(args: argparse.ArgumentParser, network_data: dict[str, str]
                 ) -> Network:
    '''
    Load existing network secrets

    :raises: ValueError, NotImplementedError
    '''

    network = Network(network_data, network_data)

    if not network.paths.network_directory_exists():
        raise ValueError(f'Network {args.network} not found')

    if args.signing_party == 'network':
        network.load_secrets()

    return network


def load_service(args, network):
    '''
    Load service and its secrets
    '''
    service = Service(
        network=network, filepath=args.contract,
    )

    if args.signing_party == 'service':
        service.load_secrets(with_private_key=True, password=args.password)
    else:
        service.load_secrets(with_private_key=False)

    return service


if __name__ == '__main__':
    main(sys.argv)
