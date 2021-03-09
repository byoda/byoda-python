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

from byoda.util import config
from byoda.util import Paths
from byoda.util import Logger
from byoda.util.secrets import CertType
from byoda.util.secrets import NetworkRootCaSecret
from byoda.util.secrets import NetworkAccountCaSecret
from byoda.util.secrets import ServiceCaSecret
from byoda.util.secrets import AccountSecret

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
    parser.add_argument('--service', '-s', type=str, default='byoda')
    parser.add_argument('--root-directory', '-r', type=str, default=_ROOT_DIR)
    parser.add_argument('--account', '-a', type=str, default='default')

    args = parser.parse_args()

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], debug=args.debug, verbose=args.verbose,
        json_out=False
    )

    root_dir = args.root_directory
    if root_dir.startswith('/tmp') and os.path.exists(root_dir):
        _LOGGER.debug(f'Wiping temporary root directory: {root_dir}')
        shutil.rmtree(root_dir)

    paths = Paths(
        args.root_directory,
        service=args.service,
        network=args.network,
        account=args.account
    )

    if args.type.lower() == CertType.NETWORK.value:
        create_network(args, paths)
    elif args.type.lower() == CertType.SERVICE.value:
        create_service(args, paths)
    elif args.type.lower() == CertType.ACCOUNT.value:
        create_account(args, paths)
    elif args.type.lower() == CertType.ACCOUNT.value:
        create_account(args, paths)


def create_network(args, paths):
    if not paths.network_directory_exists():
        paths.create_network_directory()

    if not paths.secrets_directory_exists():
        paths.create_secrets_directory()

    root_ca = NetworkRootCaSecret(
        args.network, paths=paths, root_dir=args.root_directory
    )
    if root_ca.cert_file_exists():
        raise ValueError(
            f'Root CA cert file already exists: {root_ca.cert_file}'
        )
    if root_ca.private_key_file_exists():
        raise ValueError(
            f'Root CA private key file already exists: '
            f'{root_ca.private_key_file}'
        )

    root_ca.create(issuing_ca=None, expire=100*365)
    root_ca.save()

    account_ca = NetworkAccountCaSecret(
        args.network, paths=paths, root_dir=args.root_directory
    )

    if account_ca.cert_file_exists():
        _LOGGER.warning(
            f'Overwriting Account CA cert {account_ca.cert_file} because we '
            f'have a new root CA'
        )

    if account_ca.private_key_file_exists():
        _LOGGER.warning(
            f'Overwriting Account CA private key {account_ca.private_key_file}'
            f' because we have a new root CA'
        )
    account_ca.create(issuing_ca=root_ca, expire=100*365)
    account_ca.save()

    if not paths.service_directory_exists():
        paths.create_service_directory(args.service)

    service_ca = ServiceCaSecret(
        args.network, args.service, paths=paths, root_dir=args.root_directory
    )

    if service_ca.cert_file_exists():
        _LOGGER.warning(
            f'Overwriting Service CA cert {service_ca.cert_file} because we '
            f'have a new root CA'
        )

    if service_ca.private_key_file_exists():
        _LOGGER.warning(
            f'Overwriting Account CA private key {service_ca.prvate_key_file} '
            f'because we have a new root CA'
        )

    service_ca.create(issuing_ca=root_ca, expire=100*365)
    service_ca.save()

    return {
        'NetworkRootCa': root_ca,
        'AccountCa': account_ca,
        'ServiceCa': service_ca
    }


def create_service(args):
    pass


def create_membership(args):
    pass


def create_account(args):
    if not args.account_label:
        raise argparse.ArgumentError(
            'You must provide an account label for account certs'
        )
    config.paths = Paths(account_label=args.account_label)
    paths = config.paths
    if paths.account_key_file_exists():
        raise ValueError(
            f'Private key for account {args.account_label} already exists: '
            f'{paths.account_key_file}'
        )
    if paths.account_file_exists():
        raise ValueError(
            f'Account file for account {args.account_label} already exists: '
            f'{paths.account_file}'
        )

    paths.create_account_directory()

    account_id = uuid4()
    secret = AccountSecret(account_id)
    secret.create(expire=36500)
    secret.save(
        config.paths.account_cert_file, config.paths.account_key_file
    )

    new_secret = AccountSecret(account_id)
    new_secret.load(
        config.paths.account_cert_file, config.paths.account_key_file
    )

    if secret.cert != new_secret.cert:
        raise ValueError('certs do not match')

    secret.create_shared_key()

    new_secret.load_shared_key(secret.protected_shared_key)

    if secret.shared_key != new_secret.shared_key:
        raise ValueError('RSA encrypt/decrypt failed')

    with open('/etc/passwd', 'rb') as file_desc:
        data = file_desc.read()

    ciphertext = secret.encrypt(data)

    passwords = secret.decrypt(ciphertext)

    if data != passwords:
        raise ValueError('encrypt/decrypt failed')


if __name__ == '__main__':
    main(sys.argv)
