'''
Functions shared between the pod server and the pod worker

Suported environment variables:
CLOUD: 'AWS', 'LOCAL'
BUCKET_PREFIX
NETWORK
ACCOUNT_ID
ACCOUNT_SECRET
PRIVATE_KEY_SECRET: secret to protect the private key
LOGLEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL
ROOT_DIR: where files need to be cached (if object storage is used) or stored

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import logging
from typing import Dict

from byoda import config

from byoda.datatypes import CloudType

_LOGGER = logging.getLogger(__name__)


def get_environment_vars() -> Dict:
    '''
    Parses environment variables. Returns dict with:
      - cloud: CloudType
      - bucket_prefix: str
      - network: str
      - account_id: str
      - account_secret: str
      - private_key_password: str
      - loglevel: None, 'DEBUG', 'INFO', 'WARNING', 'ERROR' or 'CRIT'
      - root_dir: str
      - roles: ['pod']
      - debug: bool
      - bootstrap: bool
      - daemonize: bool, only used for podworker
    '''

    data = {
        'cloud': CloudType(os.environ.get('CLOUD', 'LOCAL')),
        'bucket_prefix': os.environ.get('BUCKET_PREFIX'),
        'network': os.environ.get('NETWORK', config.DEFAULT_NETWORK),
        'account_id': os.environ.get('ACCOUNT_ID'),
        'account_secret': os.environ.get('ACCOUNT_SECRET'),
        'private_key_password': os.environ.get('PRIVATE_KEY_SECRET', 'byoda'),
        'loglevel': os.environ.get('LOGLEVEL', 'WARNING'),
        'root_dir': os.environ.get('ROOT_DIR', os.environ['HOME'] + '/.byoda'),
        'daemonize': os.environ.get('DAEMONIZE', ''),
        'roles': ['pod'],
    }
    data['debug'] = False

    if data.get('loglevel', '').upper() == 'DEBUG':
        data['debug'] = True

    data['bootstrap'] = False
    if os.environ.get('BOOTSTRAP', '').upper() == 'BOOTSTRAP':
        data['bootstrap'] = True

    if data.get('daemonize', '').upper() == 'FALSE':
        data['daemonize'] = False
    else:
        data['daemonize'] = True

    return data

