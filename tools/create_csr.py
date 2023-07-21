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
from uuid import uuid4

from byoda.secrets.app_data_secret import AppDataSecret

from byoda import config

from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.util.logger import Logger
from byoda.util.paths import Paths

from tests.lib.setup import setup_network


DEFAULT_NETWORK: str = "byoda.net"
DEFAULT_SERVICE_ID: str = "4294929430"
DEFAULT_TEST_DIRECTORY = '/tmp/byoda'


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

    return await setup_network(delete_tmp_dir=True)


async def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', '-n', type=str, default=DEFAULT_NETWORK)
    parser.add_argument(
        '--service_id', '-s', type=str, default=DEFAULT_SERVICE_ID
    )
    parser.add_argument('--app-id', '-a', type=str, default=uuid4())
    parser.add_argument('--type', '-t', type=str, default='app_data')
    parser.add_argument('--fqdn', '-f', type=str)
    parser.add_argument('--password', '-p', type=str)
    parser.add_argument('--out_dir', '-o', type=str, default='.')
    parser.add_argument(
        '--debug', default=False, action='store_true'
    )

    args = parser.parse_args(argv[1:])

    if args.type != 'app_data':
        raise NotImplementedError('Only App Data secrets are supported')

    if args.type == 'app_data' and not args.fqdn:
        raise ValueError('The FQDN must be specified for an App Data secret')

    global _LOGGER
    if args.debug:
        _LOGGER = Logger.getLogger(
            sys.argv[0], debug=True, json_out=False, loglevel=logging.DEBUG
        )
    else:
        _LOGGER = Logger.getLogger(
            sys.argv[0], json_out=False, loglevel=logging.WARNING
        )

    csr_filepath = f'{args.out_dir}/app-{args.fqdn}.csr'
    if os.path.exists(csr_filepath):
        raise FileExistsError(f'CSR file {csr_filepath} already exists')

    await prep_network(None, args.network)

    secret = AppDataSecret(args.service_id, config.server.network, args.fqdn)
    csr = await secret.create_csr(args.app_id)
    csr_pem = secret.csr_as_pem(csr).decode('utf-8')

    _LOGGER.debug(f'Saving CSR to {csr_filepath}')
    with open(csr_filepath, 'w') as file_desc:
        file_desc.write(csr_pem)

    private_key_pem = secret.private_key_as_pem(args.password)
    key_filepath = f'{args.out_dir}/app-{args.fqdn}.key'
    _LOGGER.debug(f'Saving private key to {key_filepath}')
    with open(key_filepath, 'w') as file_desc:
        file_desc.write(private_key_pem)

    resp = await RestApiClient.call(
        secret.paths.get(Paths.SERVICEAPP_API),
        HttpMethod.POST, data=csr_pem
    )
    if resp.status != 201:
        raise RuntimeError('Certificate signing request failed')


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
