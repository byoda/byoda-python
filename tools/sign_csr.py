#!/usr/bin/env python3

'''
Tool to sign submitted CSRs manually

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import logging
import asyncio
import argparse

from uuid import uuid4

from cryptography import x509

from byoda.secrets.appsca_secret import AppsCaSecret

from byoda.datatypes import EntityId
from byoda.datatypes import IdType

from byoda import config

from byoda.util.logger import Logger

from tests.lib.setup import setup_network


DEFAULT_NETWORK: str = "byoda.net"
DEFAULT_SERVICE_ID: str = "4294929430"
DEFAULT_TEST_DIRECTORY: str = '/tmp/byoda'


async def prep_network(test_dir: str, network_name: str = DEFAULT_NETWORK
                       ) -> dict[str, str]:
    '''
    This is a helper function to load the network, which enables
    us to use byoda.secrets.app_data_secret.AppDataSecret
    '''

    if test_dir:
        os.environ['ROOT_DIR'] = test_dir

    if not os.environ.get('ROOT_DIR'):
        os.environ['ROOT_DIR'] = DEFAULT_TEST_DIRECTORY

    os.environ['CLOUD'] = 'LOCAL'
    os.environ['NETWORK'] = network_name
    os.environ['LOGLEVEL'] = 'DEBUG'

    os.environ['PRIVATE_BUCKET'] = 'dummy'          # Not used
    os.environ['RESTRICTED_BUCKET'] = 'dummy'       # Not used
    os.environ['PUBLIC_BUCKET'] = 'dummy'           # Not used
    os.environ['ACCOUNT_ID'] = str(uuid4())         # Not used
    os.environ['ACCOUNT_SECRET'] = 'dummy'          # Not used
    os.environ['PRIVATE_KEY_SECRET'] = 'dummmy'     # Not used
    os.environ['BOOTSTRAP'] = 'dummy'               # Not used

    return await setup_network(delete_tmp_dir=False)


async def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', '-n', type=str, default=DEFAULT_NETWORK)
    parser.add_argument('--root-dir', '-r', type=str)
    parser.add_argument('--csr-file', '-c', type=str)
    parser.add_argument('--type', '-t', type=str, default='app')
    parser.add_argument(
        '--password', '-p', type=str, default=os.environ.get('BYODA_PASSWORD')
    )
    parser.add_argument('--out_dir', '-o', type=str, default='.')
    parser.add_argument(
        '--service-id', '-s', type=str, default=DEFAULT_SERVICE_ID
    )
    parser.add_argument(
        '--debug', default=False, action='store_true'
    )

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

    if args.type != 'app':
        raise NotImplementedError(
            'Only App (Data) secrets are supported'
        )

    await prep_network(args.root_dir, args.network)

    secret = AppsCaSecret(args.service_id, config.server.network)
    await secret.load(with_private_key=True, password=args.password)

    with open(args.csr_file, 'rb') as file_desc:
        csr_data = file_desc.read()

    csr = x509.load_pem_x509_csr(csr_data)
    entity_id: EntityId = secret.review_csr(csr)

    if entity_id.id_type not in (IdType.APP, IdType.APP_DATA):
        raise ValueError(
            f'This tool does not support signing {entity_id.id_type} CSRs'
        )

    cert_chain = secret.sign_csr(csr, 730)
    cert_filepath = \
        f'{args.out_dir}/{entity_id.id_type.value}{entity_id.id}.pem'

    with open(cert_filepath, 'w') as file_desc:
        file_desc.write(str(cert_chain))


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
