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
from tempfile import NamedTemporaryFile, TemporaryFile

import boto3

from byoda.datatypes import StorageType, CloudType

from .filestorage import FileStorage
from .filestorage import OpenMode, FileMode

_LOGGER = logging.getLogger(__name__)


class AwsFileStorage(FileStorage):
    '''
    Provides access to AWS S3 object storage
    '''

    def __init__(self, bucket_prefix: str, root_dir: str) -> None:
        '''
        Abstraction of storage of files on S3 object storage. Do not call this
        constructor directly but call the AwaFileStorage.setup() factory method

        :param bucket_prefix: prefix of the S3 bucket, to which '-private' and
        '-public' will be appended
        :param root_dir: directory on local file system for any operations
        involving local storage
        '''

        boto3.set_stream_logger('boto3', logging.ERROR)
        boto3.set_stream_logger('botocore', logging.ERROR)
        boto3.set_stream_logger('s3transfer', logging.ERROR)

        self.driver = boto3.client('s3')

        super().__init__(root_dir, cloud_type=CloudType.AWS)

        self.buckets = {
            StorageType.PRIVATE.value: f'{bucket_prefix}-private',
            StorageType.PUBLIC.value: f'{bucket_prefix}-public',
        }

        _LOGGER.debug(
            'Initialized boto S3 client for buckets '
            f'{self.buckets[StorageType.PRIVATE.value]} and '
            f'{self.buckets[StorageType.PUBLIC.value]}'
        )

    @staticmethod
    async def setup(bucket_prefix: str, root_dir: str):
        '''
        Factory for AwsFileStorage

        :param bucket_prefix: prefix of the storage account, to which
        'private' and 'public' will be appended
        :param root_dir: directory on local file system for any operations
        involving local storage
        '''

        return AwsFileStorage(bucket_prefix, root_dir)

    async def close_clients(self):
        '''
        Closes the azure container clients. An instance of this class can
        not be used anymore after this method is called.
        '''

        pass

    def _get_key(self, filepath: str) -> str:
        '''
        Returns the S3 key for a path to a file
        '''

        return filepath.lstrip('/')

    def get_storage_prefix(self, bucket):
        path = 'gs://{}/'.format(bucket)

        return path

    async def read(self, filepath: str, file_mode: FileMode = FileMode.BINARY,
                   storage_type=StorageType.PRIVATE) -> str:
        '''
        Reads a file from S3 storage.

        :param filepath: the S3 key; path + filename
        :param file_mode: is the data in the file text or binary
        :param storage_type: use bucket for private or public storage
        :returns: array as str or bytes with the data read from the file
        :raises: FileNotFoundError, PermissionError, OSError
        '''

        key = self._get_key(filepath)

        openmode = OpenMode.WRITE.value + file_mode.value

        try:
            with NamedTemporaryFile(openmode) as temp_desc:
                self.driver.download_fileobj(
                    self.buckets[storage_type.value], key, temp_desc,
                )
                temp_desc.flush()
                with open(temp_desc.name, 'r' + file_mode.value) as file_desc:
                    data = file_desc.read()
        except boto3.exceptions.botocore.exceptions.ClientError:
            raise FileNotFoundError(f'AWS file not found: {key}')

        _LOGGER.debug(f'Read {key} of {len(data or [])} bytes from AWS S3')

        return data

    async def write(self, filepath: str, data: str = None,
                    file_descriptor=None,
                    file_mode: FileMode = FileMode.BINARY,
                    storage_type: StorageType = StorageType.PRIVATE) -> None:
        '''
        Writes data to S3 storage.

        :param filepath: the key of the S3 object
        :param data: the data to be written to the file
        :param file_descriptor: read from the file that the file_descriptor is
        for
        :param file_mode: is the data in the file text or binary
        :param storage_type: use private or public storage bucket
        '''

        if data is None and file_descriptor is None:
            raise ValueError('Either data or file_descriptor must be provided')

        if data is not None and storage_type == StorageType.PUBLIC:
            raise ValueError(
                'writing an array of bytes to public cloud storage is not '
                'supported'
            )

        if data is not None and len(data) > 2 * 1024*1024*1024:
            raise ValueError('Writing data larger than 2GB is not supported')

        # We always have to write to local storage as AWS object upload uses
        # the local file
        if data is not None:
            if isinstance(data, str):
                data = data.encode('utf-8')

            file_descriptor = TemporaryFile(mode='w+b')
            file_descriptor.write(data)
            file_descriptor.seek(0)

        key = self._get_key(filepath)
        self.driver.upload_fileobj(
            file_descriptor, self.buckets[storage_type.value], key
        )

        _LOGGER.debug(f'Wrote {key} of {len(data or [])} bytes to AWS S3')

    async def exists(self, filepath: str,
                     storage_type: StorageType = StorageType.PRIVATE) -> bool:
        '''
        Checks if a file exists on S3 storage

        :param filepath: the key for the object on S3 storage
        :param storage_type: use private or public storage bucket
        :returns: bool on whether the key exists
        '''

        _LOGGER.debug(f'Checking if key {filepath} exists in AWS S3')
        try:
            key = self._get_key(filepath)
            self.driver.head_object(
                Bucket=self.buckets[storage_type.value], Key=key
            )
            return True
        except boto3.exceptions.botocore.exceptions.ClientError:
            return False

    async def delete(self, filepath: str,
                     storage_type: StorageType = StorageType.PRIVATE) -> bool:

        key = self._get_key(filepath)
        response = self.driver.delete_object(
            Bucket=self.buckets[storage_type.value], Key=key
        )

        return response['ResponseMetadata']['HTTPStatusCode'] == 204

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

        data = self.driver.head_bucket(Bucket=self.buckets[storage_type.value])
        region = data['ResponseMetadata']['HTTPHeaders']['x-amz-bucket-region']

        return (
            f'https://{self.buckets[storage_type.value]}.s3-{region}'
            f'.amazonaws.com/{filepath}'
        )

    async def create_directory(self, directory: str, exist_ok: bool = True,
                               storage_type: StorageType = StorageType.PRIVATE
                               ) -> bool:
        '''
        Directories do not exist on S3 storage
        '''

        return True

    async def copy(self, source: str, dest: str,
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

    async def get_folders(self, folder_path: str, prefix: str = None,
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
            path = folder['Prefix'].rstrip('/')
            if folder_path:
                path = path[len(folder_path):]

            final_path = path.split('/')[-1]
            if not prefix or final_path.startswith(prefix):
                folders.add(final_path)

        return folders
