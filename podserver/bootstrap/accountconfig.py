'''
Bootstrap the account for a pod

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID
import requests

from byoda.util.secrets import AccountSecret
from byoda.datatypes import CloudType

from byoda.util.paths import Paths

from .targetconfig import TargetConfig

_LOGGER = logging.getLogger(__name__)


class AccountConfig(TargetConfig):
    def __init__(self, cloud: CloudType, bucket_prefix: str, network: str,
                 account_id: UUID, account_key: str, account_key_secret: str,
                 paths: Paths):
        '''
        Constructor for AccountConfig

        :param cloud: the cloud we are running in
        :param bucket_prefix: the prefix for the buckets for private and
        public file storage
        :param network: the network that we are connecting to
        '''

        self.paths = paths
        self.bucket_prefix = bucket_prefix
        self.bucket = self.bucket_prefix + '_private'

        self.account_id = account_id
        self.account_key = account_key
        self.account_key_secret = account_key_secret

        self.network = network

    def exists(self):
        account_secret = AccountSecret(self.paths)
        try:
            return account_secret.cert_file_exists()
            # self.bucket.download_file(
            #     'bootstrap.env', '/var/www/wwwroot/bootstrap.env'
            # )
        except Exception as exc:
            with open('/var/www/wwwroot/index.html', 'w') as file_desc:
                file_desc.write('<HTML><BODY>bootstrap.env download failure')
                file_desc.write(f'{exc}</BODY></HTML>')

        return False

    def create(self):
        account_secret = AccountSecret(self.paths)
        csr = account_secret.create_csr(self.account_id)
        payload = {'csr': account_secret.csr_as_pem(csr).decode('utf-8')}
        url = f'https://dir.{self.network}/api/v1/network/account'

        resp = requests.post(url, json=payload)
        if resp.status_code != requests.codes.OK:
            raise RuntimeError('Certificate signing request failed')

        cert_data = resp.json()
        account_secret.from_string(
            cert_data['signed_cert'], certchain=cert_data['cert_chain']
        )
        account_secret.save(password=self.account_key_secret)
