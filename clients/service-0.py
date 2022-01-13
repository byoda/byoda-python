#!/usr/bin/env python3

'''
Tool to call GraphQL APIs against a pod

This tool does not use the Byoda modules so has no dependency
on the 'byoda-python' repository to be available on the local
file system

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import sys
import re
import argparse
import subprocess
import requests

from python_graphql_client import GraphqlClient

_ROOT_DIR = os.environ['HOME'] + '/.byoda'

MEMBER_QUERIES = {
    0: {
        'READ': '''
            query {
                person {
                    givenName
                    additionalNames
                    familyName
                    email
                    homepageUrl
                    avatarUrl
                }
            }
        ''',
        'WRITE': '''
            mutation {
                mutatePerson(
                    givenName: "Steven",
                    additionalNames: "",
                    familyName: "Hessing",
                    email: "steven@byoda.org",
                    homepageUrl: "https://byoda.org/",
                    avatarUrl: "https://some.place/avatar"
                ) {
                    givenName
                    additionalNames
                    familyName
                    email
                    homepageUrl
                    avatarUrl
                }
            }
        ''',
    },
}


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', '-n', type=str, default='byoda.net')
    parser.add_argument('--root-directory', '-r', type=str, default=_ROOT_DIR)
    parser.add_argument('--service_id', '-s', type=int, default=0)
    parser.add_argument('--password', '-p', type=str, default='byoda')
    parser.add_argument('--tempdir', '-t', type=str, default='/tmp')
    parser.add_argument('--data', '-d', type=str, default='')
    parser.add_argument('--host', '-o', type=str, default=None)
    args = parser.parse_args()

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

    cert = (member_cert_file, unprotected_key)

    if args.host:
        fqdn = args.host
    else:
        fqdn = get_cert_fqdn(member_cert_file)

    graphql_url = f'https://{fqdn}/api/v1/data/service-{args.service_id}'

    client = GraphqlClient(
        endpoint=graphql_url, cert=cert, verify=root_ca_cert
    )

    if not args.data:
        result = client.execute(
            query=MEMBER_QUERIES[args.service_id]['READ']
        )
    else:
        result = client.execute(
            query=MEMBER_QUERIES[args.service_id]['WRITE']
        )

    print(result)


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
