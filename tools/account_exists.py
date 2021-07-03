#!/usr/bin/env python3

'''
This script is executed before the webserver in the pod starts, to make
sure the desired state is in place:
- there is a valid account certificate

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import sys

import requests

from byoda.util import Paths
from byoda.util.logger import Logger
from byoda.config import DEFAULT_NETWORK

from byoda.datatypes import CloudType

from byoda.storage.filestorage import FileStorage

from podserver.bootstrap import AccountConfig

from byoda.util.secrets import AccountSecret

_LOGGER = None
LOG_FILE = '/var/www/wwwroot/logs/account.log'

BASE_URL = 'https://dir.{network}/api'

network = {
    'cloud': CloudType(os.environ.get('CLOUD', 'AWS')),
    'bucket_prefix': os.environ['BUCKET_PREFIX'],
    'network': os.environ.get('NETWORK', DEFAULT_NETWORK),
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
    logfile=LOG_FILE
)

private_object_storage = FileStorage.get_storage(
    network['cloud'], network['bucket_prefix'],
    network['root_dir']
)

# Paths class defines where all the BYODA certs/keys are stored
paths = Paths(
    root_directory=network['root_dir'], network=network['network'],
    account='pod', storage_driver=private_object_storage
)

paths.create_secrets_directory()
paths.create_account_directory()

# TODO, needs an API on the directory server
src_dir = '/podserver/byoda-python'
ca_file = (
    paths.network_directory() +
    f'/network-{network["network"]}-root-ca-cert.pem'
)
private_object_storage.copy(
    f'/{src_dir}/networks/network-{network["network"]}-root-ca-cert.pem',
    ca_file
)
_LOGGER.debug(f'CA cert for network {network["network"]} is now available')

# Desired configuration for the BYODA account
account = AccountConfig(
    network['cloud'], network['bucket_prefix'], network['network'],
    network['account_id'], network['account_secret'],
    network['private_key_password'], paths
)

if account.exists():
    _LOGGER.debug('Found an existing account')
else:
    _LOGGER.debug('Creating an account')
    account.create()

account_secret = AccountSecret(paths)
account_secret.load(password=network['private_key_password'])
key_file = account_secret.save_tmp_private_key()

api = BASE_URL.format(network=network['network']) + '/v1/network/account'
cert = (account_secret.cert_file, key_file)
resp = requests.get(api, cert=cert)
_LOGGER.debug(f'Registered account with directory server: {resp.status_code}')
