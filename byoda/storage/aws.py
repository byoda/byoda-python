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

    def __init__(self, bucket_prefix: str, cache_path: str = None) -> None:
        '''
        Abstraction of storage of files on S3 object storage

        :param bucket_prefix: prefix of the S3 bucket, to which '-private' and
        '-public' will be appended
        :param cache_path: path to the cache on the local file system
        '''

        self.driver = boto3.client('s3')

        self.cache_path = cache_path
        if cache_path:
            super().__init__(cache_path)

        self.bucket = f'{bucket_prefix}-private'
        self.public_bucket = f'{bucket_prefix}-public'

        _LOGGER.debug('Initialized boto S3 client for bucket %s', self.bucket)

    def _get_key(self, filepath: str) -> str:
        '''
        Returns the S3 key for a path to a file
        '''

        return filepath.lstrip('/')

    def read(self, filepath: str, file_mode: FileMode = FileMode.TEXT) -> str:
        '''
        Reads a file from S3 storage. If a locally cached copy is available it
        uses that instead of reading from S3 storage. If a locally cached copy
        is not available then the file is fetched from S3 storage and written
        to the local cache

        :param filepath: the S3 key (ie. path + filename)
        :param file_mode: is the data in the file text or binary
        :returns: array as str or bytes with the data read from the file
        '''

        try:
            if self.cache_path:
                data = super().read(filepath, file_mode)
                _LOGGER.debug('Read %s from cache', filepath)
                return data
        except FileNotFoundError:
            pass

        key = self._get_key(filepath)
        file_desc = super().open(
            filepath, OpenMode.WRITE, file_mode=FileMode.BINARY
        )

        self.driver.download_fileobj(self.bucket, key, file_desc)

        super().close(file_desc)

        _LOGGER.debug('Read %s from AWS S3 and saved it to %s', key, filepath)

        data = super().read(filepath, file_mode)

        return data

    def write(self, filepath: str, data: str,
              file_mode: FileMode = FileMode.TEXT) -> None:
        '''
        Writes data to S3 storage.

        :param filepath: the key of the S3 object
        :param data: the data to be written to the file
        '''
        super().write(filepath, data, file_mode=file_mode)

        key = self._get_key(filepath)
        file_desc = super().open(filepath, OpenMode.READ, file_mode)
        self.driver.upload_fileobj(file_desc, self.bucket, key)
        _LOGGER.debug('Wrote %s to AWS S3')

    def exists(self, filepath: str) -> bool:
        '''
        Checks is a file exists on S3 storage

        :param filepath: the key for the object on S3 storage
        :returns: bool on whether the key exists
        '''
        if super().exists(filepath):
            _LOGGER.debug('%s exists in local cache', filepath)
            return True
        else:
            _LOGGER.debug('Checking if key %s exists in AWS S3', filepath)
            try:
                key = self._get_key(filepath)
                self.driver.head_object(Bucket=self.bucket, Key=key)
                return True
            except boto3.exceptions.botocore.exceptions.ClientError:
                return False

    def get_url(self, public: bool = True) -> str:
        '''
        Get the URL for the public storage bucket, ie. something like
        'https://<bucket>.s3.us-west-1.amazonaws.com'
        '''

        if public:
            bucket = self.public_bucket
        else:
            bucket = self.bucket

        data = self.driver.head_bucket(Bucket=bucket)
        region = data['ResponseMetadata']['HTTPHeaders']['x-amz-bucket-region']

        return f'https://{bucket}.s3-{region}.amazonaws.com'

    def create_directory(self, directory: str, exist_ok: bool = True) -> bool:
        '''
        Directories do not exist on S3 storage but this function makes sure
        the directory exists in the local cache

        :param filepath: location of the file on the file system
        :returns: whether the file exists or not
        '''

        return super().create_directory(directory, exist_ok=exist_ok)

    def copy(self, source: str, dest: str,
             file_mode: FileMode = FileMode.TEXT) -> None:
        '''
        Copies a file from the local file system to the S3 object storage

        :param source: location of the file on the local file system
        :param dest: key for the S3 object to copy the file to
        :parm file_mode: how the file should be opened
        '''
        key = self._get_key(dest)
        self.driver.upload_file(source, self.bucket, key)
        _LOGGER.debug('Uploaded %s to S3 key %s:%s', source, self.bucket, key)

        super().copy(source, dest)
