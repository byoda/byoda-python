'''
Bring your own algorithm backend storage for the server.

The directory server uses caching storage for server and client registrations
The profile server uses noSQL storage for profile data

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import logging
from typing import Set
from tempfile import NamedTemporaryFile

import boto3

from byoda.datatypes import StorageType, CloudType

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

        super().__init__(cache_path, cloud_type=CloudType.AWS)

        self.buckets = {
            StorageType.PRIVATE.value: f'{bucket_prefix}-private',
            StorageType.PUBLIC.value: f'{bucket_prefix}-public',
        }

        _LOGGER.debug(
            'Initialized boto S3 client for buckets '
            f'{self.buckets[StorageType.PRIVATE.value]} and '
            f'{self.buckets[StorageType.PUBLIC.value]}'
        )

    def _get_key(self, filepath: str) -> str:
        '''
        Returns the S3 key for a path to a file
        '''

        return filepath.lstrip('/')

    def get_storage_prefix(self, bucket):
        path = 'gs://{}/'.format(bucket)

        return path

    def read(self, filepath: str, file_mode: FileMode = FileMode.BINARY,
             storage_type=StorageType.PRIVATE) -> str:
        '''
        Reads a file from S3 storage. If a locally cached copy is available it
        uses that instead of reading from S3 storage. If a locally cached copy
        is not available then the file is fetched from S3 storage and written
        to the local cache

        :param filepath: the S3 key; path + filename
        :param file_mode: is the data in the file text or binary
        :param storage_type: use bucket for private or public storage
        :returns: array as str or bytes with the data read from the file
        :raises: FileNotFoundError, PermissionError, OSError
        '''

        try:
            # TODO: support conditional downloads based on timestamp of local
            # file
            if self.cache_enabled:
                data = super().read(filepath, file_mode)
                _LOGGER.debug('Read %s from cache', filepath)
                return data
        except FileNotFoundError:
            pass

        key = self._get_key(filepath)

        openmode = OpenMode.WRITE.value + file_mode.value
        with NamedTemporaryFile(openmode) as file_desc:
            try:
                self.driver.download_fileobj(
                    self.buckets[storage_type.value], key, file_desc
                )
                super().move(file_desc.name, filepath)
                _LOGGER.debug(
                    f'Read {key} from AWS S3 and saved it to {filepath}'
                )
            except boto3.exceptions.botocore.exceptions.ClientError:
                raise FileNotFoundError(f'AWS file not found: {key}')

        data = super().read(filepath, file_mode)

        return data

    def write(self, filepath: str, data: str,
              file_mode: FileMode = FileMode.BINARY,
              storage_type: StorageType = StorageType.PRIVATE) -> None:
        '''
        Writes data to S3 storage.

        :param filepath: the key of the S3 object
        :param data: the data to be written to the file
        :param file_mode: is the data in the file text or binary
        :param storage_type: use private or public storage bucket
        '''

        # We always have to write to local storage as AWS object upload uses
        # the local file
        if storage_type == StorageType.PRIVATE:
            super().write(filepath, data, file_mode=file_mode)

        # TODO: can we do async / await here?
        key = self._get_key(filepath)
        file_desc = super().open(filepath, OpenMode.READ, file_mode)
        self.driver.upload_fileobj(
            file_desc, self.buckets[storage_type.value], key
        )
        _LOGGER.debug(f'Wrote {key} to AWS S3')

    def exists(self, filepath: str,
               storage_type: StorageType = StorageType.PRIVATE) -> bool:
        '''
        Checks is a file exists on S3 storage

        :param filepath: the key for the object on S3 storage
        :param storage_type: use private or public storage bucket
        :returns: bool on whether the key exists
        '''

        if (storage_type == StorageType.PRIVATE and self.cache_enabled
                and super().exists(filepath)):
            _LOGGER.debug(f'{filepath} exists in local cache')
            return True
        else:
            _LOGGER.debug(f'Checking if key {filepath} exists in AWS S3')
            try:
                key = self._get_key(filepath)
                self.driver.head_object(
                    Bucket=self.buckets[storage_type.value], Key=key
                )
                return True
            except boto3.exceptions.botocore.exceptions.ClientError:
                return False

    def delete(self, filepath: str,
               storage_type: StorageType = StorageType.PRIVATE) -> bool:

        if storage_type == StorageType.PRIVATE:
            super().delete(filepath)

        key = self._get_key(filepath)
        response = self.driver.delete_object(
            Bucket=self.buckets[storage_type.value], Key=key
        )

        return response['ResponseMetadata']['HTTPStatusCode'] == 204

    def get_url(self, storage_type: StorageType = StorageType.PRIVATE
                ) -> str:
        '''
        Get the URL for the public storage bucket, ie. something like
        'https://<bucket>.s3.us-west-1.amazonaws.com'
        '''

        data = self.driver.head_bucket(Bucket=self.buckets[storage_type.value])
        region = data['ResponseMetadata']['HTTPHeaders']['x-amz-bucket-region']

        return (
            f'https://{self.buckets[storage_type.value]}.s3-{region}'
            '.amazonaws.com/'
        )

    def create_directory(self, directory: str, exist_ok: bool = True,
                         storage_type: StorageType = StorageType.PRIVATE
                         ) -> bool:
        '''
        Directories do not exist on S3 storage but this function makes sure
        the directory exists in the local cache

        :param filepath: location of the file on the file system
        :returns: whether the file exists or not
        '''

        # We need to create the local directory regardless whether caching
        # is enabled for the Pod because upload/download uses a local file
        if storage_type == StorageType.PRIVATE:
            return super().create_directory(directory, exist_ok=exist_ok)

    def copy(self, source: str, dest: str,
             file_mode: FileMode = FileMode.BINARY,
             storage_type: StorageType = StorageType.PRIVATE,
             exist_ok=True) -> None:
        '''
        Copies a file from the local file system to the S3 object storage

        :param source: location of the file on the local file system
        :param dest: key for the S3 object to copy the file to
        :parm file_mode: how the file should be opened
        '''

        key = self._get_key(dest)
        dirpath, filename = self.get_full_path(source, create_dir=False)
        self.driver.upload_file(
            dirpath + filename, self.buckets[storage_type.value], key
        )
        _LOGGER.debug(
            f'Uploaded {source} to S3 key {self.buckets[storage_type.value]}'
            f': {key}'
        )

        # We populate the local disk cache also with the copy
        if storage_type == StorageType.PRIVATE and self.cache_enabled:
            super().copy(source, dest)

    def get_folders(self, folder_path: str, prefix: str = None,
                    storage_type: StorageType = StorageType.PRIVATE
                    ) -> Set[str]:
        '''
        AWS S3 supports emulated folders through keys that end with a '/'
        '''
        # For AWS S3, the folder path must contain a '/' at the end
        folder_path = folder_path.rstrip('/') + '/'
        result = self.driver.list_objects(
            Bucket=self.buckets[storage_type.value],
            Prefix=folder_path, Delimiter='/'
        )
        folders = set()
        for folder in result.get('CommonPrefixes', []):
            final_path = folder['Prefix'].rstrip('/').split('/')[-1]
            if not prefix or final_path.startswith(prefix):
                folders.add(folder['Prefix'])

        return folders
