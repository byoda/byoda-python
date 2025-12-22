'''
Bring your own data & algorithm CEPH storage for the PDS.

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import logging

from typing import Self
from logging import Logger
from logging import getLogger

from byoda.datatypes import StorageType, CloudType

from botocore.config import Config

from byoda.datatypes import StorageType

from .aws import AwsFileStorage

_LOGGER: Logger = getLogger(__name__)


class CephFileStorage(AwsFileStorage):
    __slots__: list[str] = ['driver', 'buckets', 'endpoint']

    '''
    Provides access to AWS S3 object storage
    '''

    def __init__(self, private_bucket: str, restricted_bucket: str,
                 public_bucket: str, root_dir: str,
                 access_key_id: str, secret_access_key: str,
                 ceph_endpoint: str) -> None:
        '''
        Abstraction of storage of files on S3 object storage. Do not call this
        constructor directly but call the AwaFileStorage.setup() factory method

        :param private_bucket:
        :param restricted_bucket:
        :param public_bucket:
        :param root_dir: directory on local file system for any operations
        involving local storage
        '''

        # We need to use signature version 's3' for Ceph compatibility as we
        # get errors with the default 's3v4' signature version

        self.endpoint: str = ceph_endpoint.rstrip('/')

        config: dict[str, str] = {
            'endpoint_url': ceph_endpoint,
            'aws_access_key_id': access_key_id,
            'aws_secret_access_key': secret_access_key,
            'region_name': 'default',
            'config': Config(signature_version='s3')
        }

        super().__init__(
            private_bucket, restricted_bucket, public_bucket, root_dir,
            config=config, cloud_type=CloudType.CEPH
        )
        _LOGGER.debug(f'Using storage endpoint {ceph_endpoint}')

    @staticmethod
    async def setup(private_bucket: str, restricted_bucket: str,
                    public_bucket: str, root_dir: str,
                    access_key_id: str, secret_access_key: str,
                    ceph_endpoint: str) -> Self:
        '''
        Factory for AwsFileStorage

        :param private_bucket:
        :param restricted_bucket:
        :param public_bucket:
        :param root_dir: directory on local file system for any operations
        involving local storage
        '''

        return CephFileStorage(
            private_bucket, restricted_bucket, public_bucket, root_dir,
            access_key_id, secret_access_key, ceph_endpoint
        )

    def get_url(self, filepath: str = None,
                storage_type: StorageType = StorageType.PRIVATE) -> str:
        '''
        Get the URL for the public storage bucket, ie. something like
        'https://<bucket>.s3.us-west-1.amazonaws.com'

        :param filepath: path to the file
        :param storage_type: return the url for the private or public storage
        :returns: str
        '''

        if filepath is None:
            filepath = ''

        bucket: str = self.get_bucket(storage_type)
        return f'{bucket}/{filepath}'

    def get_bucket(self, storage_type: StorageType
                   = StorageType.PRIVATE) -> str:
        '''
        Get the bucket name for the specified storage type

        :param storage_type: return the bucket for the private or public
        storage
        :returns: str
        '''

        return f'{self.endpoint}/{self.buckets[storage_type.value]}'

    async def get_folders(self, folder_path: str, prefix: str = None,
                          storage_type: StorageType = StorageType.PRIVATE
                          ) -> set[str]:

        raise NotImplementedError(
            'RadosGW throws SignatureDoesNotMatch errors on boto3.list_objects[_v2] calls'
        )