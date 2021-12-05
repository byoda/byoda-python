'''
Bring your own data & algorithm backend storage for the server running on
Azure.

For Azure, we use 'Managed Identity' assigned to a VM for authentication

Assigning a managed identity to an existing VM using aAzure CLL:
  az vm identity assign -g <resource-group> -n <vm-name>

Azure rights to assign:
  Contributor
  Storage Blob Data Contributor

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import List, Dict


from azure.identity import DefaultAzureCredential

# Import the client object from the SDK library
from azure.storage.blob import ContainerClient

from byoda.datatypes import StorageType

from .filestorage import FileStorage
from .filestorage import OpenMode, FileMode

_LOGGER = logging.getLogger(__name__)


class AzureFileStorage(FileStorage):
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

        self.credential: DefaultAzureCredential = DefaultAzureCredential()

        self.cache_path: str = cache_path
        if cache_path:
            super().__init__(cache_path)

        domain = 'blob.core.windows.net'

        self.buckets: Dict[str:str] = {
            StorageType.PRIVATE:
                f'{bucket_prefix}{StorageType.PRIVATE.value}.{domain}',
            StorageType.PUBLIC:
                f'{bucket_prefix}{StorageType.PUBLIC.value}.{domain}'
        }
        # Azure enforces the use of containers so we keep a cache of
        # authenticated ContainerClient instances for each container
        # that we use.
        self.clients: Dict[StorageType, Dict[str, ContainerClient]] = {
            StorageType.PRIVATE: {},
            StorageType.PUBLIC: {},
        }

        _LOGGER.debug(
            'Initialized Azure Blob SDK for buckets '
            f'{self.buckets[StorageType.PRIVATE]} and '
            f'{self.buckets[StorageType.PUBLIC]}'
        )

    def _get_container_client(self, filepath: str,
                              storage_type: StorageType = StorageType.PRIVATE
                              ) -> ContainerClient:
        '''
        Gets the container client for the container or creates it
        and stores it in the pool if it doesn't already exist
        '''

        container, blob = filepath.split('/', 2)

        if container not in self.clients[storage_type.value]:
            url = self.buckets[storage_type.value]
            container_client = ContainerClient(
                url, container, credential=self.credential
            )
            self.clients[storage_type.value] = container_client
        else:
            container_client = self.clients[storage_type.value]

        return container_client, container, blob

    def read(self, filepath: str, file_mode: FileMode = FileMode.TEXT,
             storage_type=StorageType.PRIVATE) -> str:
        '''
        Reads a file from S3 storage. If a locally cached copy is available it
        uses that instead of reading from S3 storage. If a locally cached copy
        is not available then the file is fetched from S3 storage and written
        to the local cache

        :param filepath: the S3 key; path + filename
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

        container_client, container, blob = self._get_container_client(
            filepath, storage_type=storage_type
        )

        if not container_client.exists():
            raise FileNotFoundError(f'Container {container} does not exist')

        blob_client = container_client.get_blob_client(blob)

        # Download the data from the blob and save it to disk cache
        # TODO: conditional get to allow multiple pods share object storage
        # TODO: can we do async / await here?
        download_stream = blob_client.download_blob()
        data = download_stream.readall()
        file_desc = super().open(
            filepath, OpenMode.WRITE, file_mode=file_mode
        )
        file_desc.write(data)
        super().close(file_desc)

        _LOGGER.debug(
            f'Read {container}/{blob} from Azure object storage and saved it '
            f'to {filepath}'
        )

        return data

    def write(self, filepath: str, data: str,
              file_mode: FileMode = FileMode.TEXT,
              storage_type: StorageType = StorageType.PRIVATE) -> None:
        '''
        Writes data to Azure Blob storage.

        :param filepath: the full path to the blob
        :param data: the data to be written to the file
        '''

        if storage_type == StorageType.PRIVATE:
            super().write(filepath, data, file_mode=file_mode)

        container_client, container, blob = self._get_container_client(
            filepath, storage_type=storage_type
        )

        blob_client = container_client.get_blob_client(blob)

        file_desc = super().open(filepath, OpenMode.READ, file_mode)
        blob_client.upload_blob(file_desc)

        _LOGGER.debug(f'Write {container}/{blob} to Azure Storage Account')

    def exists(self, filepath: str,
               storage_type: StorageType = StorageType.PRIVATE) -> bool:
        '''
        Checks is a file exists on Azure object storage

        :param filepath: the key for the object on S3 storage
        :returns: bool on whether the key exists
        '''
        if storage_type == StorageType.PRIVATE and super().exists(filepath):
            _LOGGER.debug(f'{filepath} exists in local cache')
            return True
        else:
            container_client, container, blob = self._get_container_client(
                filepath, storage_type=storage_type
            )
            if container_client.exists():
                _LOGGER.debug(
                    f'{container}/{blob} exists in Azure storage account'
                )
                return True
            else:
                _LOGGER.debug(
                    f'{container}/{blob} does not exist in '
                    'Azure storage account'
                )
                return False

    def get_url(self, storage_type: StorageType = StorageType.PRIVATE) -> str:
        '''
        Get the URL for the public storage bucket, ie. something like
        'https://<bucket>.s3.us-west-1.amazonaws.com'
        '''

        return self.buckets[storage_type]

    def create_directory(self, directory: str, exist_ok: bool = True,
                         storage_type: StorageType = StorageType.PRIVATE
                         ) -> bool:
        '''
        Directories do not exist on Azure storage but this function makes sure
        the directory exists in the local cache and the container exists on
        Azure object storage

        :param directory: location of the file on the file system
        :returns: whether the file exists or not
        '''

        if storage_type == StorageType.PRIVATE:
            super().create_directory(directory, exist_ok=exist_ok)

        container_client, container, blob = self._get_container_client(
            directory, storage_type=storage_type
        )

        container_client.create_container()
        _LOGGER.debug(f'Created container {container}')

    def copy(self, source: str, dest: str,
             file_mode: FileMode = FileMode.TEXT,
             storage_type: StorageType = StorageType.PRIVATE) -> None:
        '''
        Copies a file from the local file system to the Azure storage account

        Note that we only store data in local cache for the private container

        :param source: location of the file on the local file system
        :param dest: key for the S3 object to copy the file to
        :parm file_mode: how the file should be opened
        '''

        container_client, container, blob = self._get_container_client(
            dest, storage_type=StorageType.PRIVATE
        )

        blob_client = container_client.get_blob_client(blob)
        file_desc = super().open(source, OpenMode.READ, file_mode)
        blob_client.upload_blob(file_desc)

        _LOGGER.debug(f'Uploaded {source} to {container}:{blob}')

        # We populate the local disk cache also with the copy
        if storage_type == StorageType.PRIVATE:
            super().copy(source, dest)

    def get_folders(self, folder_path: str, prefix: str = None) -> List[str]:
        '''
        Azure Storage let's you walk through blobs whose name start
        with a prefix
        '''

        container_client, container, blob = self._get_container_client(
            folder_path, storage_type=StorageType.PRIVATE
        )
        folders = [container_client.walk_blobs(name_starts_with=prefix)]

        if prefix:
            folders = [
                folder for folder in folders if folder.startswith(prefix)
            ]
            _LOGGER.debug(
                f'Found {len(folders)} blobs with prefix {prefix} '
                f'under {container}'
            )
        else:
            _LOGGER.debug(f'Found {len(folders)} blobs under {container}')

        return folders
