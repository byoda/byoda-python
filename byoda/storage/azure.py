'''
Bring your own data & algorithm backend storage for the server running on
Azure.

For Azure, we use 'Managed Identity' assigned to a VM for authentication

Assigning a managed identity to an existing VM using aAzure CLL:
  az vm identity assign -g <resource-group> -n <vm-name>

Azure rights to assign:
  Storage Blob Data Contributor

Azure SDK documentation
container_client: https://docs.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob.containerclient?view=azure-python
blob_client: https://docs.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob.blobclient?view=azure-python

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import Set, Dict
from tempfile import NamedTemporaryFile

from azure.identity import DefaultAzureCredential

# Import the client object from the SDK library
from azure.storage.blob import ContainerClient, BlobClient
from azure.core.exceptions import ResourceNotFoundError

from byoda.datatypes import StorageType, CloudType

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

        super().__init__(cache_path, cloud_type=CloudType.AZURE)

        domain = 'blob.core.windows.net'
        self.buckets: Dict[str:str] = {
            StorageType.PRIVATE.value:
                f'{bucket_prefix}{StorageType.PRIVATE.value}.{domain}',
            StorageType.PUBLIC.value:
                f'{bucket_prefix}{StorageType.PUBLIC.value}.{domain}'
        }
        # We pre-authenticate for the byoda container on each storage account
        self.clients: Dict[StorageType, ContainerClient] = {
            StorageType.PRIVATE.value: ContainerClient(
                self.buckets[StorageType.PRIVATE.value], 'byoda',
                credential=self.credential
            ),
            StorageType.PUBLIC.value: ContainerClient(
                self.buckets[StorageType.PUBLIC.value], 'byoda',
                credential=self.credential
            ),
        }

        if not self.clients[StorageType.PRIVATE.value].exists():
            self.clients[StorageType.PRIVATE.value].create_container()

        if not self.clients[StorageType.PUBLIC.value].exists():
            self.clients[StorageType.PUBLIC.value].create_container()

        _LOGGER.debug(
            'Initialized Azure Blob SDK for buckets '
            f'{self.buckets[StorageType.PRIVATE.value]} and '
            f'{self.buckets[StorageType.PUBLIC.value]}'
        )

    def _get_container_client(self, filepath: str,
                              storage_type: StorageType = StorageType.PRIVATE
                              ) -> ContainerClient:
        '''
        Gets the container client for the container "byoda" on the
        Azure storage account for private or public storage
        '''

        filepath = filepath.lstrip('/')

        _LOGGER.debug(
            f'Finding container client for {storage_type.value} '
            f'with blob {filepath}'
        )

        container_client = self.clients[storage_type.value]

        return container_client, filepath

    def _get_blob_client(self, filepath: str,
                         storage_type: StorageType = StorageType.PRIVATE
                         ) -> BlobClient:
        '''
        Gets the blob client for a blob under container "byoda" on the
        Azure storage account for private or public storage
        '''
        container_client, blob = self._get_container_client(
            filepath, storage_type
        )

        client = container_client.get_blob_client(blob)

        return client

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

        blob_client = self._get_blob_client(filepath)

        # Download the data from the blob and save it to disk cache
        # TODO: can we do async / await here?
        try:
            download_stream = blob_client.download_blob()
            data = download_stream.readall()
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(
                f'Azure blob {filepath} not found in container "byoda" for '
                f'storage {self.buckets[storage_type.value]}: {exc}'
            )

        openmode = OpenMode.WRITE.value + file_mode.value
        with NamedTemporaryFile(openmode) as file_desc:
            file_desc.write(data)
            super().move(file_desc.name, filepath)

        _LOGGER.debug(
            f'Read blob "byoda/{filepath}" for bucket '
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

        if storage_type == StorageType.PRIVATE:
            super().write(filepath, data, file_mode=file_mode)

        blob_client = self._get_blob_client(filepath)

        super().write(filepath, data)
        file_desc = super().open(filepath, OpenMode.READ, file_mode)
        blob_client.upload_blob(file_desc, overwrite=True)

        _LOGGER.debug(
            f'wrote blob "byoda/{filepath}" for bucket '
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
            blob_client = self._get_blob_client(filepath)
            _LOGGER.debug(
                f'Checking if blob "byoda/{filepath}" exists in the Azure '
                f'storage account {self.buckets[storage_type.value]}'
            )
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

        blob_client = self._get_blob_client(
            filepath, storage_type=storage_type
        )

        blob_client.delete_blob()
        _LOGGER.debug(
            f'Deleted byoda/{filepath} from Azure storage account '
            f'{self.buckets[storage_type.value]}'
        )

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
        the directory exists in the local cache

        :param directory: location of the file on the file system
        :returns: whether the file exists or not
        '''

        if storage_type == StorageType.PRIVATE:
            super().create_directory(directory, exist_ok=exist_ok)

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

        blob_client = self._get_blob_client(dest)
        file_desc = super().open(source, OpenMode.READ, file_mode.BINARY)
        blob_client.upload_blob(file_desc, overwrite=exist_ok)

        _LOGGER.debug(
            f'Uploaded {source} to "byoda/{dest}" on Azure storage account '
            f'{self.buckets[storage_type.value]}'
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

        container_client, blob = self._get_container_client(
            folder_path, storage_type=storage_type
        )
        if prefix and not prefix.startswith(blob):
            prefix = f'{blob.rstrip("/")}/{prefix}'

        folders = set()
        iterator = container_client.walk_blobs(name_starts_with=folder_path)
        for folder in iterator:
            if (folder.name.endswith('/')
                    and (not prefix or folder.name.startswith(prefix))):
                full_path = folder.name
                path_components = full_path.rstrip('/').split('/')
                if path_components:
                    folder_name = path_components[-1]
                else:
                    folder_name = folder.name

                folders.add(folder_name)

        if prefix:
            _LOGGER.debug(
                f'Found {len(folders)} blobs with prefix {prefix} '
                f'under {blob}'
            )
        else:
            _LOGGER.debug(
                f'Found {len(folders)} blobs in the "byoda" container on '
                f'Azure storage account {self.buckets[storage_type.value]}'
            )

        return folders
