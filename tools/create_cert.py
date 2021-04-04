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

from byoda.util import Paths
from byoda.util import Logger
from byoda.datatypes import CertType, CsrSource
from byoda.util.secrets import NetworkRootCaSecret
from byoda.util.secrets import NetworkAccountsCaSecret
from byoda.util.secrets import NetworkServicesCaSecret
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
    parser.add_argument('--member', '-m', type=str, default='')

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
        root_directory=args.root_directory,
        network_name=args.network,
        account_alias=args.account
    )

    if args.type.lower() == CertType.NETWORK.value:
        create_network(args, paths)

    if args.type.lower() == CertType.SERVICE.value:
        create_service(args, paths)

    if args.type.lower() == CertType.ACCOUNT.value:
        create_account(args, paths)


def create_network(args, paths):
    if not paths.network_directory_exists():
        paths.create_network_directory()

    if not paths.secrets_directory_exists():
        paths.create_secrets_directory()

    root_ca = NetworkRootCaSecret(paths=paths)
    if root_ca.cert_file_exists():
        raise ValueError(
            f'Root CA cert file already exists: {root_ca.cert_file}'
        )
    if root_ca.private_key_file_exists():
        raise ValueError(
            f'Root CA private key file already exists: '
            f'{root_ca.private_key_file}'
        )

    root_ca.create(expire=100*365)
    root_ca.save()

    accounts_ca = NetworkAccountsCaSecret(paths=paths)

    if accounts_ca.cert_file_exists():
        _LOGGER.warning(
            f'Overwriting Account CA cert {accounts_ca.cert_file} because we '
            f'have a new root CA'
        )

    if accounts_ca.private_key_file_exists():
        _LOGGER.warning(
            f'Overwriting Account CA private key '
            f'{accounts_ca.private_key_file} because we have a new root CA'
        )
    csr = accounts_ca.create_csr()
    root_ca.review_csr(csr, source=CsrSource.LOCAL)
    certchain = root_ca.sign_csr(csr, 365 * 100)
    accounts_ca.add_signed_cert(certchain)
    accounts_ca.save()

    services_ca = NetworkServicesCaSecret(paths=paths)

    if services_ca.cert_file_exists():
        _LOGGER.warning(
            f'Overwriting Service CA cert {services_ca.cert_file} because we '
            f'have a new root CA'
        )

    if services_ca.private_key_file_exists():
        _LOGGER.warning(
            f'Overwriting Account CA private key {services_ca.prvate_key_file}'
            f' because we have a new root CA'
        )

    services_ca.create_csr()
    root_ca.review_csr(csr, source=CsrSource.LOCAL)
    certchain = root_ca.sign_csr(csr, 365 * 100)
    services_ca.add_signed_cert(certchain)
    services_ca.save()

    return {
        'NetworkRootCa': root_ca,
        'AccountCa': accounts_ca,
        'ServicesCa': services_ca
    }


def create_service(args, paths):
    if not paths.service_directory_exists(paths.service):
        paths.create_service_directory(paths.service)
    pass


def create_membership(args):
    pass


def create_account(args, paths):
    if not args.account:
        raise argparse.ArgumentError(
            'You must provide an account label for account certs'
        )

    paths.create_secrets_directory()
    paths.create_account_directory()

    account_id = uuid4()
    account_secret = AccountSecret(paths)
    csr = account_secret.create_csr(account_id)     # noqa
    raise NotImplementedError
    # TODO: Need to submit CSR to dir.byoda.net and retrieve the signed cert
    account_secret.save()


if __name__ == '__main__':
    main(sys.argv)
