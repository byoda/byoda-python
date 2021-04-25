'''
Bring your own algorithm backend storage for the server.

The directory server uses caching storage for server and client registrations
The profile server uses noSQL storage for profile data

:maintainer : Steven Hessing (stevenhessing@live.com)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import logging

import boto3

from .filestorage import FileStorage
from .filestorage import OpenMode, FileMode

_LOGGER = logging.getLogger(__name__)


class AwsFileStorage(FileStorage):
    '''
    Provides access to AWS S3 object storage
    '''

    def __init__(self, bucket, cache_path=None):
        self.driver = boto3.client('s3')

        self.cache_path = cache_path
        if cache_path:
            super().__init__(cache_path)

        self.bucket = bucket
        _LOGGER.debug('Initialized boto S3 client for bucket %s', self.bucket)

    def read(self, filepath, file_mode=FileMode.TEXT):
        try:
            if self.cache_path:
                data = super().read(filepath, file_mode)
                _LOGGER.debug('Read %s from cache', filepath)
                return data
        except FileNotFoundError:
            pass

        file_desc = super().open(filepath, OpenMode.READ, file_mode)

        self.driver.meta.download_fileobj(self.bucket, filepath, file_desc)

        data = super().read(filepath, file_mode)
        _LOGGER.debug('Read %s from AWS S3')

        return data

    def write(self, filepath, data, file_mode=FileMode.TEXT):
        super().write(filepath, data, file_mode=file_mode)

        file_desc = super().open(filepath, OpenMode.WRITE, file_mode)
        self.driver.upload_fileobj(file_desc, self.bucket, filepath)
        _LOGGER.debug('Wrote %s to AWS S3')

    def exists(self, filepath):
        if super().exists(filepath):
            _LOGGER('%s exists in local cache', filepath)
            return True
        else:
            _LOGGER.debug('Checking if %s exists in AWS S3', filepath)
            self.driver.head_object(Bucket=self.bucket, Key=filepath)
