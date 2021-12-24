'''
Bring your own data & algorithm backend storage for the server running on
Azure.

Extra steps for installing Azure Storage SDK:
  sudo apt install libgirepository1.0-dev libcairo2-dev python3.9-dev \
      gir1.2-secret-1


For Azure, we use 'Managed Identity' assigned to a VM for authentication

Assigning a managed identity to an existing VM using aAzure CLL:
  az vm identity assign -g <resource-group> -n <vm-name>

Azure rights to assign:
  Storage Blob Data Contributor

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from typing import Set, Dict


from azure.identity import DefaultAzureCredential

# Import the client object from the SDK library
from azure.storage.blob import ContainerClient
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from byoda.datatypes import StorageType

from .filestorage import FileStorage
from .filestorage import OpenMode, FileMode

_LOGGER = logging.getLogger(__name__)


class AzureFileStorage(FileStorage):
    '''
    Provides access to Azure object (aka 'blob') storage
    '''

    def __init__(self, bucket_prefix: str, cache_path: str = None) -> None:
        '''
        Abstraction of storage of files on Azure storage accounts

        :param bucket_prefix: prefix of the storage account, to which
        'private' and 'public' will be appended
        :param cache_path: path to the cache on the local file system
        '''

        self.credential: DefaultAzureCredential = DefaultAzureCredential()

        super().__init__(cache_path)

        domain = 'blob.core.windows.net'
        self.buckets: Dict[str:str] = {
            StorageType.PRIVATE.value:
                f'{bucket_prefix}{StorageType.PRIVATE.value}.{domain}',
            StorageType.PUBLIC.value:
                f'{bucket_prefix}{StorageType.PUBLIC.value}.{domain}'
        }
        # Azure enforces the use of containers so we keep a cache of
        # authenticated ContainerClient instances for each container
        # that we use.
        self.clients: Dict[StorageType, Dict[str, ContainerClient]] = {
            StorageType.PRIVATE.value: {},
            StorageType.PUBLIC.value: {},
        }

        _LOGGER.debug(
            'Initialized Azure Blob SDK for buckets '
            f'{self.buckets[StorageType.PRIVATE.value]} and '
            f'{self.buckets[StorageType.PUBLIC.value]}'
        )

    def _get_container_client(self, filepath: str,
                              storage_type: StorageType = StorageType.PRIVATE
                              ) -> ContainerClient:
        '''
        Gets the container client for the container or creates it
        and stores it in the pool if it doesn't already exist
        '''

        if '/' not in filepath:
            filepath = filepath + '/'
        else:
            filepath = filepath.lstrip('/')

        container, blob = filepath.split('/', 1)

        _LOGGER.debug(
            f'Finding container client for {container} with blob {blob}'
        )
        if container not in self.clients[storage_type.value]:
            url = self.buckets[storage_type.value]
            container_client = ContainerClient(
                url, container, credential=self.credential
            )
            self.clients[storage_type.value][container] = container_client
            if not container_client.exists():
                container_client.create_container()
        else:
            container_client = self.clients[storage_type.value][container]

        return container_client, container, blob

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

        try:
            # TODO: support conditional downloads based on timestamp of local
            # file
            if storage_type == StorageType.PRIVATE and self.cache_enabled:
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
        # TODO: can we do async / await here?
        try:
            download_stream = blob_client.download_blob()
            data = download_stream.readall()
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(
                f'Azure blob {blob} not found in {container}: {exc}'
            )

        file_desc = super().open(
            filepath, OpenMode.WRITE, file_mode=file_mode
        )
        file_desc.write(data)
        super().close(file_desc)

        _LOGGER.debug(f'Read {container}/{blob} from Azure object storage')

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

        if storage_type == StorageType.PRIVATE:
            super().write(filepath, data, file_mode=file_mode)

        container_client, container, blob = self._get_container_client(
            filepath, storage_type=storage_type
        )

        blob_client = container_client.get_blob_client(blob)

        super().write(filepath, data)
        file_desc = super().open(filepath, OpenMode.READ, file_mode)
        blob_client.upload_blob(file_desc, overwrite=True)

        _LOGGER.debug(f'Write {container}/{blob} to Azure Storage Account')

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
            container_client, container, blob = self._get_container_client(
                filepath, storage_type=storage_type
            )
            _LOGGER.debug(
                f'Checking if key {filepath} exists in the Azure storage '
                f'account {self.buckets[storage_type.value]}'
            )
            blob_client = container_client.get_blob_client(blob)
            if blob_client.exists():
                _LOGGER.debug(
                    f'{filepath} exists in Azure storage account '
                    f'{self.buckets[storage_type.value]}'
                )
                return True
            else:
                _LOGGER.debug(
                    f'{filepath} does not exist in Azure storage account '
                    f'{self.buckets[storage_type.value]}'
                )
                return False

    def delete(self, filepath: str,
               storage_type: StorageType = StorageType.PRIVATE) -> bool:

        if storage_type == StorageType.PRIVATE:
            super().delete(filepath)

        container_client, container, blob = self._get_container_client(
                filepath, storage_type=storage_type
            )

        if blob:
            try:
                container_client.delete_blob(blob)
            except ResourceNotFoundError:
                pass
        else:
            container_client.delete_container()

    def get_url(self, storage_type: StorageType = StorageType.PRIVATE) -> str:
        '''
        Get the URL for the public storage bucket, ie. something like
        https://<storage_account>.blob.core.windows.net/<prefix>-[private|public]
        '''

        return f'https://{self.buckets[storage_type.value]}/'

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

        try:
            container_client.create_container()
        except ResourceExistsError:
            pass

        _LOGGER.debug(f'Created container {container}')

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

        container_client, container, blob = self._get_container_client(
            dest, storage_type=StorageType.PRIVATE
        )

        blob_client = container_client.get_blob_client(blob)
        file_desc = super().open(source, OpenMode.READ, file_mode.BINARY)
        blob_client.upload_blob(file_desc, overwrite=exist_ok)

        _LOGGER.debug(f'Uploaded {source} to {container}:{blob}')

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

        container_client, container, blob = self._get_container_client(
            folder_path, storage_type=storage_type
        )
        folders = set()
        for folder in container_client.walk_blobs(name_starts_with=prefix):
            if (folder.name.endswith('/')
                    and (not prefix or folder.name.startswith(prefix))):
                folders.add(folder.name)

        if prefix:
            _LOGGER.debug(
                f'Found {len(folders)} blobs with prefix {prefix} '
                f'under {container}'
            )
        else:
            _LOGGER.debug(f'Found {len(folders)} blobs under {container}')

        return folders
