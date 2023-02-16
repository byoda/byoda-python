#!/usr/bin/env python3

'''
Backup and restore data in the to/from object storage

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import sys
import tarfile
import asyncio
import argparse
import subprocess

from byoda.storage import FileStorage
from byoda.datatypes import CloudType


async def main(argv: list):
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument('--backup', '-b', action='store_false', default=True)
    parser.add_argument('--target', '-t', type=str, default='/byoda/mongodb')
    parser.add_argument('--root-directory', '-r', type=str, default='/byoda')
    args = parser.parse_args()
    if args.backup:
        await backup(args.target, CloudType.AZURE)


async def backup(target: str, cloud_type: CloudType, root_dir: str = '/byoda'):
    if not os.path.exists(target):
        raise FileNotFoundError(f'Target {target} does not exist')

    basename = f'{os.path.basename(target)}_backup.tar.gz'
    temp_file = f'/tmp/{basename}'
    if (os.path.exists(temp_file)):
        raise (f'Tempfile {temp_file} already exists')

    services = get_services(root_dir)
    tar_file = tarfile.open(temp_file, 'w:bz2')

    for service_id in services:
        subprocess.run(
            [
                '/usr/bin/mongodump', '-h', 'localhost', '-p', '27017', '-d',
                'service-4294929430', '-o', f'/tmp/mongodb/service-{service_id}'
            ]
        )

    # if os.path.isdir(target):
    #    for root, dirs, files in os.walk(target):
    #        for file in files:
    #            full_path = os.path.join(root, file)
    #            tar_file.add(
    #                full_path, arcname=os.path.relpath(
    #                    full_path, os.path.join(target, '..')
    #                )
    #           )
    #else:
    #    tar_file.add(target)

    tar_file.close()

    fs = await FileStorage.get_storage(cloud_type, 'byoda', '/byoda')
    upload_file = open(temp_file, 'rb')
    await fs.write(f'private/backup/{basename}', file_descriptor=upload_file)


def get_services(root_dir: str) -> list[int]:
    files = os.listdir(root_dir)
    services: list[int] = []
    for file in files:
        if file.startswith('service-'):
            service_id = file[len('service-'):]
            services.append(service_id)

    return services


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
