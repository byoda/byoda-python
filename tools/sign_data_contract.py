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

from byoda.datamodel import Network, Service
from byoda.servers import ServiceServer
from byoda.datamodel.service import RegistrationStatus

from byoda.storage.filestorage import FileStorage

from byoda.util import SignatureType
from byoda.util import Logger
from byoda.util import Paths

from byoda.util.api_client import HttpMethod, RestApiClient
from byoda.secrets import ServiceSecret
from byoda.secrets import NetworkDataSecret

from byoda import config

_LOGGER = None

_ROOT_DIR = os.environ['HOME'] + '/.byoda'


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument(
        '--signing-party', '-s', type=str, default=None,
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

    config.server = ServiceServer()
    config.server.network = network
    config.server.service = service

    if not args.local:
        service.registration_status = service.get_registration_status()
        if service.registration_status == RegistrationStatus.Unknown:
            raise ValueError('Please use "create_service_secrets.py" script first')

    schema = service.schema.json_schema

    if 'signatures' not in schema:
        schema['signatures'] = {}

    if not args.local:
        response = service.register_service()
        if response.status_code != 200:
            raise ValueError(
                f'Failed to register service: {response.status_code}'
            )

    result = None
    if (not args.signing_party
            or args.signing_party == SignatureType.SERVICE.value):
        try:
            create_service_signature(service)
            result = True
        except Exception as exc:
            _LOGGER.exception(f'Failed to get service signature: {exc}')
            result = False

    if (result is not False and (
            not args.signing_party
            or args.signing_party == SignatureType.NETWORK.value)):
        result = create_network_signature(service, args)

    if not result:
        _LOGGER.error('Failed to get the network signature')
        sys.exit(1)

    if not args.root_directory.startswith('/'):
        # Hack to make relative paths work with the FileStorage class
        args.root_directory = os.getcwd()

    storage_driver = FileStorage(args.root_directory)
    service.schema.save(
        service.paths.get(Paths.SERVICE_FILE), storage_driver=storage_driver
    )


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

    if not args.signing_party or args.signing_party == 'service':
        service.load_secrets(with_private_key=True, password=args.password)
    else:
        service.load_secrets(with_private_key=False)

    return service


def create_service_signature(service):
    schema = service.schema.json_schema

    if SignatureType.SERVICE.value in service.schema.json_schema['signatures']:
        raise ValueError('Schema has already been signed by the service')

    if (service.schema.json_schema['signatures'].get(
            SignatureType.NETWORK.value)):
        raise ValueError('Schema has already been signed by the network')

    service.schema.create_signature(
        service.data_secret, SignatureType.SERVICE
    )
    _LOGGER.debug(f'Added service signature {schema["signatures"]["service"]}')


def create_network_signature(service, args) -> bool:
    '''
    Add network signature to the service schema/data contract,
    either locally or by a directory server over the network

    :returns: was signing the schema/contract successful?
    '''

    network = service.network

    if (SignatureType.SERVICE.value
            not in service.schema.json_schema['signatures']):
        raise ValueError('Schema has not been signed by the service')

    if (service.schema.json_schema['signatures'].get(
                SignatureType.NETWORK.value)):
        raise ValueError('Schema has already been signed by the network')

    # We first verify the service signature before we add the network
    # signature
    service.schema.verify_signature(
        service.data_secret, SignatureType.SERVICE
    )

    if args.local:
        # When signing locally, the service contract gets updated
        # with the network signature
        network.data_secret = NetworkDataSecret(network.paths)
        network.data_secret.load(with_private_key=True, password=args.password)
        service.schema.create_signature(
            network.data_secret, SignatureType.NETWORK
        )
    else:
        service_secret = ServiceSecret(None, service.service_id, network)
        service_secret.load(with_private_key=True)
        response = RestApiClient.call(
            service.paths.get(Paths.NETWORKSERVICE_API),
            HttpMethod.PATCH,
            secret=service_secret,
            data=service.schema.json_schema,
        )
        if response.status_code == 200:
            data = response.json()
            if data['errors']:
                _LOGGER.debug('Validation of service by the network failed')
                for error in data['errors']:
                    _LOGGER.debug(f'Validation error: {error}')

                return False
            else:
                response = RestApiClient.call(
                    service.paths.get(Paths.NETWORKSERVICE_API),
                    HttpMethod.GET,
                    secret=service_secret,
                    service_id=service.service_id
                )
                if response.status_code == 200:
                    service.schema.json_schema = response.json()
                    service.registration_status = \
                        RegistrationStatus.SchemaSigned
                else:
                    return False

    _LOGGER.debug(
        'Added network signature '
        f'{service.schema.json_schema["signatures"]["network"]}'
    )


if __name__ == '__main__':
    main(sys.argv)
