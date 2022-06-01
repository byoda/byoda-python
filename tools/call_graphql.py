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
import re
import orjson
import argparse
import subprocess

from python_graphql_client import GraphqlClient

from tests.lib.graphql_queries import MUTATE_PERSON

_ROOT_DIR = os.environ['HOME'] + '/.byoda'


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', '-n', type=str, default='byoda.net')
    parser.add_argument('--root-directory', '-r', type=str, default=_ROOT_DIR)
    parser.add_argument('--service_id', '-s', type=str, default='4294929430')
    parser.add_argument('--password', '-p', type=str, default='byoda')
    parser.add_argument('--tempdir', '-t', type=str, default='/tmp')
    parser.add_argument('--data-file', '-f', type=str, default='data.json')
    args = parser.parse_args()

    with open(args.data_file) as file_desc:
        data = orjson.load(file_desc)

    root_dir = args.root_directory
    network_dir = f'{root_dir}/network-{args.network}'
    account_dir = f'{network_dir}/account-pod'
    member_dir = f'{account_dir}/service-{args.service_id}'

    root_ca_cert = f'{network_dir}/network-{args.network}-root-ca-cert.pem'
    account_cert_file = f'{account_dir}/pod-cert.pem'
    member_cert_file = (
        f'{member_dir}/network-{args.network}-'
        f'member-{args.service_id}-cert.pem'
    )

    unprotected_key = decrypt_private_key(args)

    fqdn = get_cert_fqdn(member_cert_file)

    graphql_url = f'https://{fqdn}/api/v1/data/service-{args.service_id}'

    client = GraphqlClient(
        endpoint=graphql_url,
        verify=root_ca_cert,
        cert=(member_cert_file, unprotected_key)
    )

    result = client.execute(
        query=MUTATE_PERSON.format(
            given_name=data['person']['given_name'],
            additional_names=data['person']['additional_names'],
            family_name=data['person']['family_name'],
            email=data['person']['email'],
            homepage_url=data['person']['homepage_url'],
            avatar_url=data['person']['avatar_url']
        )
    )

    if 'data' in result:
        print(f'Data returned by GraphQL: {result["data"]}')


def get_cert_fqdn(certfile):
    '''
    Parses the common name out of the cert file
    '''

    rx = re.compile(
        '''Subject.*Name.*C=.*ST=.*L=.*O=.*,CN=(.*\.members-\d+\.byoda.net)'''
    )
    with open(certfile) as file_desc:
        for line in file_desc:
            match = rx.search(line)
            if match:
                print(f'Found CN in cert file {certfile}: {match.group(1)}')
                return match.group(1)


def decrypt_private_key(args: argparse.ArgumentParser) -> str:
    '''
    Decrypt the private key for the membership so we can use it with
    the Python 'requests' module

    :returns: the filepath on the local file system for the unprotected
    private key
    '''

    account_key_file = (
        f'{args.root_directory}/private/network-{args.network}'
        f'-account-pod-member-{args.service_id}.key'
    )

    dest_filepath = f'{args.tempdir}/private-{args.service_id}.key'

    cmd = [
        'openssl', 'rsa', '-in', account_key_file, '-out',
        dest_filepath, '-passin', f'pass:{args.password}'
    ]

    result = subprocess.run(cmd, capture_output=True)

    if result.returncode != 0:
        raise ValueError(f'Unable to decrypt private key: {account_key_file}')

    return dest_filepath


if __name__ == '__main__':
    main(sys.argv)
