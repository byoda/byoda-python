'''
Bring your own data & algorithm backend storage for the server running on
Google Cloud Platform.

For Azure, we use 'Managed Identity' assigned to a VM for authentication

Assigning a managed identity to an existing VM using aAzure CLL:
  az vm identity assign -g <resource-group> -n <vm-name>

Azure rights to assign:
  Storage Blob Data Contributor

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import logging
from typing import Set, Dict

from google.cloud import storage
from google.cloud.storage.bucket import Bucket
from google.cloud.storage.blob import Blob

from byoda.datatypes import StorageType, CloudType

from .filestorage import FileStorage
from .filestorage import FileMode

_LOGGER = logging.getLogger(__name__)


class GcpFileStorage(FileStorage):
    '''
    Provides access to GCS (Google Cloud Storage)
    '''

    def __init__(self, bucket_prefix: str, cache_path: str = None) -> None:
        '''
        Abstraction of storage of files on GCS object storage

        :param bucket_prefix: prefix of the GCS bucket, to which '-private' and
        '-public' will be appended
        :param cache_path: path to the cache on the local file system. If no
        cache_path is specified, a local cache will not be used. This is the
        configuration to use when running multiple pods in parallel
        '''

        if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
            raise ValueError(
                'GCP requires environment variable '
                '"GOOGLE_APPLICATION_CREDENTIALS" to point file with '
                'credentials'
            )

        super().__init__(cache_path, cloud_type=CloudType.GCP)

        self._client = storage.Client()

        self.domain = 'storage.cloud.google.com'
        self.buckets: Dict[str:str] = {
            StorageType.PRIVATE.value:
                f'{bucket_prefix}-{StorageType.PRIVATE.value}',
            StorageType.PUBLIC.value:
                f'{bucket_prefix}-{StorageType.PUBLIC.value}'
        }
        # We keep a cache of Buckets. We call them 'clients' to
        # remain consistent with the implementations for AWS and Azure
        self.clients: Dict[StorageType, Dict[str, Bucket]] = {
            StorageType.PRIVATE.value: Bucket(
                self._client, self.buckets[StorageType.PRIVATE.value]
            ),
            StorageType.PUBLIC.value: Bucket(
                self._client, self.buckets[StorageType.PUBLIC.value]
            )
        }

        _LOGGER.debug(
            'Initialized GCP SDK for buckets '
            f'{self.buckets[StorageType.PRIVATE.value]} and '
            f'{self.buckets[StorageType.PUBLIC.value]}'
        )

    def _get_blob_client(self, filepath: str,
                         storage_type: StorageType = StorageType.PRIVATE
                         ) -> Blob:
        '''
        Gets the blob client for the file
        '''

        blob = self.clients[storage_type.value].blob(filepath)

        return blob

    def read(self, filepath: str, file_mode: FileMode = FileMode.BINARY,
             storage_type=StorageType.PRIVATE) -> str:
        '''
        Reads a file from Azure Object storage. If a locally cached copy is
        available it uses that instead of reading from S3 storage. If a
        locally cached copy is not available then the file is fetched from
        object storage and written to the local cache

        :param filepath: container + path + filename
        :param file_mode: is the data in the file text or binary
        :param storage_type: use private or public storage account
        :returns: array as str or bytes with the data read from the file
        '''

        blob = self._get_blob_client(filepath, storage_type)

        try:
            if storage_type == StorageType.PRIVATE and self.cache_enabled:
                data = super().read(filepath, file_mode)
                _LOGGER.debug('Read %s from cache', filepath)
                return data
        except FileNotFoundError:
            pass

        data = blob.download_as_bytes()

        if storage_type == StorageType.PRIVATE and self.cache_enabled:
            super().write(filepath, data, file_mode)

        _LOGGER.debug(
            f'Read {filepath} from GCP bucket'
            f'{self.buckets[storage_type.value]}'
        )

        return data

    def write(self, filepath: str, data: str,
              file_mode: FileMode = FileMode.BINARY,
              storage_type: StorageType = StorageType.PRIVATE) -> None:
        '''
        Writes data to Azure Blob storage.

        :param filepath: the full path to the blob
        :param data: the data to be written to the file
        :param file_mode: is the data in the file text or binary
        :param storage_type: use private or public storage account
        '''

        blob = self._get_blob_client(filepath, storage_type)

        with blob.open(f'w{file_mode.value}') as file_desc:
            file_desc.write(data)

        if storage_type == StorageType.PRIVATE and self.cache_enabled:
            super().write(filepath, data, file_mode)

        _LOGGER.debug(
            f'Wrote {filepath} to GCP bucket '
            f'{self.buckets[storage_type.value]}'
        )

    def exists(self, filepath: str,
               storage_type: StorageType = StorageType.PRIVATE) -> bool:
        '''
        Checks is a file exists on Azure object storage

        :param filepath: the key for the object on S3 storage
        :param storage_type: use private or public storage account
        :returns: bool on whether the key exists
        '''

        if (storage_type == StorageType.PRIVATE and self.cache_enabled
                and super().exists(filepath)):
            _LOGGER.debug(f'{filepath} exists in local cache')
            return True
        else:
            blob = self._get_blob_client(filepath, storage_type)
            _LOGGER.debug(
                f'Checking if key {filepath} exists in GCP bucket '
                f'{self.buckets[storage_type.value]}'
            )
            if blob.exists():
                _LOGGER.debug(
                    f'{filepath} exists in GCP storage bucket'
                    f'{self.buckets[storage_type.value]}'
                )
                return True
            else:
                _LOGGER.debug(
                    f'{filepath} does not exist GCP storage bucket '
                    f'{self.buckets[storage_type.value]}'
                )
                return False

    def delete(self, filepath: str,
               storage_type: StorageType = StorageType.PRIVATE) -> bool:

        if storage_type == StorageType.PRIVATE:
            super().delete(filepath)

        blob = self._get_blob_client(filepath, storage_type)
        blob.delete()

    def get_url(self, storage_type: StorageType = StorageType.PRIVATE) -> str:
        '''
        Get the URL for the public storage bucket, ie. something like
        'https://storage.cloud.google.com/<prefix>-[private|public]'
        '''

        return f'https://{self.domain}/{self.buckets[storage_type.value]}/'

    def create_directory(self, directory: str, exist_ok: bool = True,
                         storage_type: StorageType = StorageType.PRIVATE
                         ) -> bool:
        '''
        Directories do not exist on GCP object storage but this function makes
        sure the directory exists in the local cache

        :param directory: location of the file on the file system
        :returns: whether the file exists or not
        '''

        if storage_type == StorageType.PRIVATE:
            super().create_directory(directory, exist_ok=exist_ok)

        # We need to create the local directory regardless whether caching
        # is enabled for the Pod because upload/download uses a local file
        _LOGGER.debug(f'Created container {directory} on local storage')

    def copy(self, source: str, dest: str,
             file_mode: FileMode = FileMode.BINARY,
             storage_type: StorageType = StorageType.PRIVATE,
             exist_ok=True) -> None:
        '''
        Copies a file from the local file system to the Azure storage account

        Note that we only store data in local cache for the private container

        :param source: location of the file on the local file system
        :param dest: key for the S3 object to copy the file to
        :parm file_mode: how the file should be opened
        '''

        data = super().read(source, file_mode)

        blob = self._get_blob_client(dest, storage_type)
        with blob.open(f'w{file_mode.value}') as file_desc:
            file_desc.write(data)

        _LOGGER.debug(
            f'Uploaded {source} to {dest} on GCP bucket '
        )

        # We populate the local disk cache also with the copy
        if storage_type == StorageType.PRIVATE:
            super().copy(source, dest)

    def get_folders(self, folder_path: str, prefix: str = None,
                    storage_type: StorageType = StorageType.PRIVATE
                    ) -> Set[str]:
        '''
        Azure Storage let's you walk through blobs whose name start
        with a prefix
        '''

        bucket = self.clients[storage_type.value]
        folders = set()

        folder_prefix = folder_path.rstrip('/') + '/'

        if prefix:
            folder_prefix = folder_prefix + prefix
        else:
            folder_prefix = folder_prefix

        for folder in bucket.list_blobs(prefix=folder_prefix):
            _LOGGER.debug(f'Found blob: {folder.name}')
            path = folder.name[len(folder_path):]
            if '/' in path:
                folder = path[:path.index('/') + 1]
                if not prefix or folder.startswith(prefix):
                    folders.add(folder)

        if prefix:
            _LOGGER.debug(
                f'Found {len(folders)} blobs with prefix {prefix} '
                f'under {folder_path} in GCP bucket {bucket.name}'
            )
        else:
            _LOGGER.debug(
                f'Found {len(folders)} blobs under {folder_path} in '
                f'GCP bucket {bucket.name}'
        )

        return folders
