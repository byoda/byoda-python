'''
Bootstrap the account for a pod

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID

from byoda.datatypes import CloudType

from byda.storage import FileStorage
from .targetconfig import TargetConfig

_LOGGER = logging.getLogger(__name__)


class AccountConfig(TargetConfig):
    def __init__(self, cloud: CloudType, bucket_prefix: str, network: str,
                 account_id: UUID, account_key: str, account_key_secret: str,
                 object_storage: FileStorage):
        '''
        Constructor for AccountConfig

        :param cloud: in which cloud are we running
        :param bucket_prefix: the prefix for the buckets for private and
        public file storage
        :param network: the network that we are connecting to
        '''

        self.bucket_prefix = bucket_prefix
        self.object_storage = object_storage
        self.bucket = self.storage.Bucket(self.bucket_prefix + '_private')

        self.account_id = account_id
        self.account_key = account_key

    def exists(self):
        try:
            self.bucket.download_file(
                'bootstrap.env', '/var/www/wwwroot/bootstrap.env'
            )
        except Exception as exc:
            with open('/var/www/wwwroot/index.html', 'w') as file_desc:
                file_desc.write('<HTML><BODY>bootstrap.env download failure')
                file_desc.write(f'{exc}</BODY></HTML>')

    def create(self):
        pass
