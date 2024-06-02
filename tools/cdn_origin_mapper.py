#!/usr/bin/env python3

'''
Hashes a plain-text password
'''

import os

import json
import shutil
import logging
import filecmp
import subprocess

from yaml import safe_load as yaml_safe_loader

_LOGGER = logging.getLogger(__name__)

CONFIG_FILE: str = '/opt/byoda/config.yml'

HOSTS_FILE: str = '/opt/byoda/hosts-byohost'
RESTRICTED_MAP_FILE: str = '/tmp/members-restricted.map'
PUBLIC_MAP_FILE: str = '/tmp/members-public.map'
RESTRICTED_MAP_BACKUP: str = f'{RESTRICTED_MAP_FILE}.backup'
PUBLIC_MAP_BACKUP: str = f'{PUBLIC_MAP_FILE}.backup'

TMP_DIR: str = '/tmp/cdn-maps'


def get_cdn_ips(filepath: str) -> list[str]:
    cdn_ips: list[str] = []
    with open(filepath, 'r') as file_desc:
        host_line: str
        for host_line in file_desc:
            host_line.strip()
            if not host_line or host_line[0] == '#':
                continue
            cdn_ip: str = host_line.split(' ')[0]
            cdn_ips.append(cdn_ip)

    return cdn_ips


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)

    with open(CONFIG_FILE, 'r') as file_desc:
        config: any = yaml_safe_loader(file_desc)
        origins_dir: str = config['cdnserver']['origins_dir']

    origins: list[dict[str, int | str | dict[str, str]]] = []
    for filename in os.listdir(origins_dir):
        with open(f'{origins_dir}/{filename}', 'r') as file_desc:
            origin_data: any = json.loads(file_desc.read())
            origins.append(origin_data)

    origins.sort(key=lambda x: x['member_id'])

    generate_map(origins, 'restricted', RESTRICTED_MAP_FILE)
    generate_map(origins, 'public', PUBLIC_MAP_FILE)

    files_changed: bool = False
    if not os.path.exists(RESTRICTED_MAP_BACKUP):
        _LOGGER.debug(f'Backup file {RESTRICTED_MAP_BACKUP} does not exist')
        files_changed = True
    elif not filecmp.cmp(RESTRICTED_MAP_FILE, RESTRICTED_MAP_BACKUP):
        _LOGGER.debug(
            f'Files {RESTRICTED_MAP_FILE} and {RESTRICTED_MAP_BACKUP} differ'
        )
        files_changed = True

    if not os.path.exists(PUBLIC_MAP_BACKUP):
        _LOGGER.debug(f'Backup file {RESTRICTED_MAP_BACKUP} does not exist')
        files_changed = True
    elif not filecmp.cmp(PUBLIC_MAP_FILE, PUBLIC_MAP_BACKUP):
        _LOGGER.debug(
            f'Files {PUBLIC_MAP_FILE} and {PUBLIC_MAP_BACKUP} differ'
        )
        files_changed = True

    if files_changed:
        cdn_ips: list[str] = get_cdn_ips('/opt/byoda/hosts-byohost')
        for cdn_ip in cdn_ips:
            subprocess.run(
                [
                    'rsync', '-avc',
                    '-e', 'ssh -i /home/ubuntu/.ssh/id_ed25519-cdnkeys',
                    RESTRICTED_MAP_FILE, PUBLIC_MAP_FILE,
                    'ubuntu@' + cdn_ip + ':/etc/angie/conf.d/maps'
                ]
            )
            os.rename(RESTRICTED_MAP_FILE, RESTRICTED_MAP_BACKUP)
            os.rename(PUBLIC_MAP_FILE, PUBLIC_MAP_BACKUP)
    else:
        _LOGGER.debug('No changes in the map files')


def generate_map(origins: list[dict[str, int | str | dict[str, str]]],
                 map_type: str, filepath: str) -> None:
    os.makedirs(TMP_DIR, exist_ok=True)
    with open(filepath, 'w') as file_desc:
        for origin in origins:
            line: str = (
                f'{origin["service_id"]}:{origin["member_id"]}    '
                f'{origin["buckets"][map_type]};'
            )
            file_desc.write(line + '\n')


if __name__ == '__main__':
    main()
