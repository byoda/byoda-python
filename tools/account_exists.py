#!/usr/bin/env python3

'''
This script is executed before the webserver in the pod starts to make
sure the desired state is in place:
- there is a valid account certificate

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import sys

from byoda.util import Paths
from byoda.util.logger import Logger

from byoda.datatypes import CloudType

from byoda.storage.filestorage import FileStorage

from podserver.bootstrap import AccountConfig

_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/pod.log'

network = {
    'cloud': CloudType(os.environ.get('CLOUD', 'AWS')),
    'bucket_prefix': os.environ['BUCKET_PREFIX'],
    'network': os.environ.get('NETWORK', 'byoda.net'),
    'account_id': os.environ.get('ACCOUNT_ID'),
    'account_secret': os.environ.get('ACCOUNT_SECRET'),
    'private_key_password': os.environ.get('PRIVATE_KEY_SECRET', 'byoda'),
    'loglevel': os.environ.get('LOGLEVEL', 'WARNING'),
    'root_dir': '/byoda',
    'roles': ['pod'],
}

debug = False
if network['loglevel'] == 'DEBUG':
    debug = True

_LOGGER = Logger.getLogger(
    sys.argv[0], json_out=False, debug=debug, loglevel=network['loglevel'],
    logfile=None
)

private_object_storage = FileStorage.get_storage(
    network['cloud'], network['bucket_prefix'] + '-private',
    network['root_dir']
)

# Paths class defines where all the BYODA certs/keys are stored
paths = Paths(
    root_directory=network['root_dir'], network_name=network['network'],
    account_alias='pod', storage_driver=private_object_storage
)

paths.create_secrets_directory()
paths.create_account_directory()

# TODO, needs an API on the directory server
private_object_storage.copy(
    '/podserver/byoda-python/networks/network-byoda.net-root-ca-cert.pem',
    paths.network_directory() + '/network-byoda.net-root-ca-cert.pem'
)

# Desired configuration for the BYODA account
account = AccountConfig(
    network['cloud'], network['bucket_prefix'], network['network'],
    network['account_id'], network['account_secret'],
    network['private_key_password'], paths
)

if not account.exists():
    account.create()
