#!/usr/bin/env python3

'''
Manages certitificates:
- create root CA for
  - account
  - service

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import sys
import os
import argparse
import shutil
from uuid import uuid4

from byoda.util import Logger

from byoda.datamodel import Network, Service, Account, Member, Server

from byoda.datatypes import CertType, CloudType, ServerRole
from byoda.datastore import DocumentStoreType


from byoda.util.secrets import NetworkRootCaSecret
from byoda.util.secrets import MembersCaSecret

from byoda import config


_LOGGER = None

_ROOT_DIR = os.environ['HOME'] + '/.byoda'


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument(
        '--type', '-t', choices=CertType.__members__,
        default=CertType.ACCOUNT.value
    )
    parser.add_argument('--network', '-n', type=str, default='test')
    parser.add_argument('--service', '-s', type=str, default='default')
    parser.add_argument('--service-id', '-i', type=str, default='0')
    parser.add_argument('--root-directory', '-r', type=str, default=_ROOT_DIR)
    parser.add_argument('--account', '-a', type=str, default='pod')
    parser.add_argument('--account-id', '-c', type=str, default=None)
    parser.add_argument('--member', '-m', type=str, default=None)
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

    if args.local is False:
        raise NotImplementedError(
            'Getting certs signed over the Internet is not yet supported'
        )

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], debug=args.debug, verbose=args.verbose,
        json_out=False
    )

    root_dir = args.root_directory
    if root_dir.startswith('/tmp') and os.path.exists(root_dir):
        _LOGGER.debug(f'Wiping temporary root directory: {root_dir}')
        shutil.rmtree(root_dir)

    request_type = args.type.lower()
    args.type = CertType(request_type)

    if args.type == CertType.NETWORK:
        network = create_network(args, network_data)
    else:
        network = load_network(args, network_data)

    # Need to set role to allow loading of unsigned services
    network.roles = [ServerRole.Pod]
    network.load_services('./services/')

    if args.type in (CertType.NETWORK, CertType.SERVICE):
        service = create_service(args, network)
    else:
        if args.type in (CertType.MEMBERSHIP, CertType.APP):
            service = load_service(args, network)

    config.server = Server()
    config.server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType('LOCAL'),
        bucket_prefix='byoda',
        root_dir='/byoda'
    )

    if args.type == CertType.ACCOUNT:
        account = create_account(args, network)
    elif args.type == CertType.MEMBERSHIP:
        account = load_account(args, network)

    if args.type == CertType.MEMBERSHIP:
        create_membership(account, service, service.members_ca)


def create_network(args: argparse.ArgumentParser, network_data: dict[str, str]
                   ) -> Network:
    network = Network.create(
        network_data['network'], network_data['root_dir'],
        network_data['private_key_password']
    )

    return network


def load_network(args: argparse.ArgumentParser, network_data: dict[str, str]
                 ) -> Network:
    '''
    Load existing network secrets

    :raises: ValueError, NotImplementedError
    '''

    network = Network(network_data, network_data)

    if not network.paths.network_directory_exists():
        raise ValueError(f'Network {args.network} not found')

    network.root_ca = NetworkRootCaSecret(network.paths)

    network.load_secrets()

    return network


def create_service(args, network: Network):
    service = Service(
        service=args.service, service_id=args.service_id, network=network
    )
    service.create_secrets(network.services_ca)


def load_service(args, network):
    service = Service(
        network=network, filepath="services/default.json"
    )
    service.load_secrets(with_private_key=True, password=args.password)

    return service


def create_membership(account, service,
                      members_ca: MembersCaSecret) -> Member:
    member = account.join(service=service, members_ca=members_ca)
    return member


def create_account(args, network) -> Account:
    if not args.account:
        raise argparse.ArgumentError(
            'You must provide an account label and ID for account certs'
        )

    account_id = args.account_id
    if not account_id:
        account_id = uuid4()

    account = Account(account_id, network)
    account.create_secrets(network.accounts_ca)
    return account


def load_account(args, network):
    account = Account(args.account_id, network)
    account.load_secrets()
    return account


if __name__ == '__main__':
    main(sys.argv)
