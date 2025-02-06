'''
Functions shared between the pod server and the pod worker

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os

from uuid import UUID
from logging import Logger, getLogger

from byoda.datatypes import CloudType

from byoda import config

_LOGGER: Logger = getLogger(__name__)

DEFAULT_DB_CONNECTION_STRING: str = \
    'postgresql://postgres:byoda@postgres/byoda'


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
      - worker_loglevel: None, 'DEBUG', 'INFO', 'WARNING', 'ERROR' or 'CRIT'
      - log_queries: bool
      - root_dir: str
      - host_root_dir: str
      - roles: ['pod']
      - debug: bool
      - bootstrap: bool
      - daemonize: bool, only used for pod_worker
      - custom_domain: str
      - shared_webserver: bool
      - manage_custom_domain_cert: bool
      - cdn_app_id: str
      - cdn_fqdn: str
      - cdn_origin_site_id: str
      - moderation_fqdn: str
      - moderation_app_id: str
      - join_service_ids: list[int]
      - db_connection: str
      - http_port: int
      - host_ip: str
    '''

    data: dict[str, str | bool | int] = {
        'cloud': CloudType(os.environ.get('CLOUD', 'LOCAL')),
        'private_bucket': os.environ.get('PRIVATE_BUCKET'),
        'restricted_bucket': os.environ.get('RESTRICTED_BUCKET'),
        'public_bucket': os.environ.get('PUBLIC_BUCKET'),
        'network': os.environ.get('NETWORK', config.DEFAULT_NETWORK),
        'account_id': os.environ.get('ACCOUNT_ID'),
        'account_secret': os.environ.get('ACCOUNT_SECRET'),
        'private_key_password': os.environ.get('PRIVATE_KEY_SECRET', 'byoda'),
        'debug': os.environ.get('DEBUG', False),
        'loglevel': os.environ.get('LOGLEVEL', 'WARNING'),
        'logdir': os.environ.get('LOGDIR', None),
        'worker_loglevel': os.environ.get('WORKER_LOGLEVEL', 'WARNING'),
        'root_dir': os.environ.get('ROOT_DIR', '/byoda'),
        'host_root_dir': os.environ.get('HOST_ROOT_DIR', '/byoda'),
        'daemonize': os.environ.get('DAEMONIZE', ''),
        'custom_domain': os.environ.get('CUSTOM_DOMAIN'),
        'shared_webserver': bool(os.environ.get('SHARED_WEBSERVER')),
        'manage_custom_domain_cert':
            os.environ.get('MANAGE_CUSTOM_DOMAIN_CERT') is not None,
        'roles': ['pod'],
        'cdn_app_id': os.environ.get('CDN_APP_ID'),
        'cdn_fqdn': os.environ.get('CDN_FQDN'),
        'cdn_origin_site_id': os.environ.get('CDN_ORIGIN_SITE_ID'),
        'moderation_fqdn': os.environ.get('MODERATION_FQDN'),
        'moderation_app_id': os.environ.get('MODERATION_APP_ID'),
        'db_connection': os.environ.get(
            'DB_CONNECTION', DEFAULT_DB_CONNECTION_STRING
        ),
        'host_ip': os.environ.get('HOST_IP'),
        'http_port': int(os.environ.get('HTTP_PORT', 8000)),
        'join_service_ids': [
            int(x) for x in os.environ.get('JOIN_SERVICE_IDS', '').split(',')
            if x
        ],
    }

    if not data['db_connection']:
        data['db_connection'] = DEFAULT_DB_CONNECTION_STRING

    if data['cdn_app_id']:
        data['cdn_app_id'] = UUID(data['cdn_app_id'])

    if data['cloud'] == CloudType.LOCAL and not data['root_dir']:
        data['root_dir'] = os.environ['HOME'] + '/.byoda'

    if data.get('loglevel', '').upper() == 'DEBUG':
        data['debug'] = True

    if data.get('worker_loglevel', '').upper() == 'DEBUG':
        data['debug'] = True

    data['bootstrap'] = False
    if os.environ.get('BOOTSTRAP', '').upper() == 'BOOTSTRAP':
        data['bootstrap'] = True

    data['log_requests'] = True
    if os.environ.get('LOG_REQUESTS', 'TRUE').upper() == 'FALSE':
        data['log_requests'] = False

    if data.get('daemonize', '').upper() == 'FALSE':
        data['daemonize'] = False
    else:
        data['daemonize'] = True

    _LOGGER.debug(f'Collected settings: {data}')
    return data
