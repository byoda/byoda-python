'''
Functions shared between the pod server and the pod worker

Suported environment variables:
CLOUD: 'AWS', 'LOCAL'
PRIVATE_BUCKET
RESTRICTED_BUCKET
PUBLIC_BUCKET
NETWORK
ACCOUNT_ID
ACCOUNT_SECRET
PRIVATE_KEY_SECRET: secret to protect the private key
LOGLEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL
ROOT_DIR: where files need to be cached (if object storage is used) or stored

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from logging import getLogger
from byoda.util.logger import Logger

from byoda.datatypes import CloudType

from byoda import config

_LOGGER: Logger = getLogger(__name__)


def get_environment_vars() -> dict:
    '''
    Parses environment variables. Returns dict with:
      - cloud: CloudType
      - private_bucket: str
      - restricted_bucket: str
      - public_bucket: str
      - network: str
      - account_id: str
      - account_secret: str
      - private_key_password: str
      - loglevel: None, 'DEBUG', 'INFO', 'WARNING', 'ERROR' or 'CRIT'
      - root_dir: str
      - roles: ['pod']
      - debug: bool
      - bootstrap: bool
      - daemonize: bool, only used for pod_worker
    '''

    data = {
        'cloud': CloudType(os.environ.get('CLOUD', 'LOCAL')),
        'private_bucket': os.environ.get('PRIVATE_BUCKET'),
        'restricted_bucket': os.environ.get('RESTRICTED_BUCKET'),
        'public_bucket': os.environ.get('PUBLIC_BUCKET'),
        'network': os.environ.get('NETWORK', config.DEFAULT_NETWORK),
        'account_id': os.environ.get('ACCOUNT_ID'),
        'account_secret': os.environ.get('ACCOUNT_SECRET'),
        'private_key_password': os.environ.get('PRIVATE_KEY_SECRET', 'byoda'),
        'loglevel': os.environ.get('LOGLEVEL', 'WARNING'),
        'logfile': os.environ.get('LOGFILE', None),
        'worker_loglevel': os.environ.get('WORKER_LOGLEVEL', 'WARNING'),
        'root_dir': os.environ.get('ROOT_DIR'),
        'daemonize': os.environ.get('DAEMONIZE', ''),
        'custom_domain': os.environ.get('CUSTOM_DOMAIN'),
        'shared_webserver': os.environ.get('SHARED_WEBSERVER') is not None,
        'manage_custom_domain_cert':
            os.environ.get('MANAGE_CUSTOM_DOMAIN_CERT') is not None,
        'roles': ['pod'],
        'moderation_fqdn': os.environ.get('MODERATION_FQDN'),
        'moderation_app_id': os.environ.get('MODERATION_APP_ID'),
    }

    if data['cloud'] == CloudType.LOCAL and not data['root_dir']:
        data['root_dir'] = os.environ['HOME'] + '/.byoda'

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
