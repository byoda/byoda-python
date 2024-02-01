'''
Bring your own data & algorithm backend storage for the server running on
Google Cloud Platform.

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from logging import getLogger
from byoda.util.logger import Logger
from tempfile import TemporaryFile

from google.cloud import storage
from google.api_core import exceptions as gcp_exceptions

from google.cloud.storage.bucket import Bucket
from google.cloud.storage.blob import Blob

from byoda.datatypes import StorageType, CloudType

from .filestorage import FileStorage
from .filestorage import FileMode

_LOGGER: Logger = getLogger(__name__)


class GcpFileStorage(FileStorage):
    __slots__: list[str] = ['_client', 'domain', 'buckets', 'clients']
    '''
    Provides access to GCS (Google Cloud Storage)
    '''

    def __init__(self, private_bucket: str, restricted_bucket: str,
                 public_bucket: str, root_dir: str) -> None:
        '''
        Abstraction of storage of files on GCS object storage. Do not call
        this constructor but call the GcpFileStorage.setup() factory method

        :param private_bucket:
        :param restricted_bucket:
        :param public_bucket:
        :param root_dir: directory on local file system for any operations
        involving local storage
        '''

        super().__init__(root_dir, cloud_type=CloudType.GCP)

        self._client = storage.Client()

        self.domain = 'storage.cloud.google.com'
        self.buckets: dict[str:str] = {
            StorageType.PRIVATE.value: private_bucket,
            StorageType.RESTRICTED.value: restricted_bucket,
            StorageType.PUBLIC.value: public_bucket
        }
        # We keep a cache of Buckets. We call them 'clients' to
        # remain consistent with the implementations for AWS and Azure
        self.clients: dict[StorageType, dict[str, Bucket]] = {
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

    @staticmethod
    async def setup(private_bucket: str, restricted_bucket: str,
                    public_bucket: str, root_dir: str = None):
        '''
        Factory for GcpFileStorage

        :param private_bucket:
        :param restricted_bucket:
        :param public_bucket:
        :param root_dir: directory on local file system for any operations
        involving local storage
        '''

        return GcpFileStorage(
            private_bucket, restricted_bucket, public_bucket, root_dir
        )

    def _get_blob_client(self, filepath: str,
                         storage_type: StorageType = StorageType.PRIVATE
                         ) -> Blob:
        '''
        Gets the S3 client for the file
        '''

        blob = self.clients[storage_type.value].blob(filepath)

        return blob

    async def close_clients(self):
        '''
        Closes any open connections. An instance of this class can not
        be used anymore after this method is called.
        '''

        pass

    async def read(self, filepath: str, file_mode: FileMode = FileMode.BINARY,
                   storage_type=StorageType.PRIVATE) -> str:
        '''
        Reads a file from GCP S3 storage.

        :param filepath: container + path + filename
        :param file_mode: is the data in the file text or binary
        :param storage_type: use private or public storage account
        :returns: array as str or bytes with the data read from the file
        '''

        blob = self._get_blob_client(filepath, storage_type)

        try:
            data = blob.download_as_bytes()
        except gcp_exceptions.NotFound as exc:
            raise FileNotFoundError(
                f'GCP bucket client could not find {filepath}: {exc}'
            )

        _LOGGER.debug(
            f'Read {len(data or [])} for {filepath} from GCP bucket'
            f'{self.buckets[storage_type.value]}'
        )

        return data

    async def write(self, filepath: str, data: str = None,
                    file_descriptor=None,
                    file_mode: FileMode = FileMode.BINARY,
                    storage_type: StorageType = StorageType.PRIVATE,
                    content_type: str = None) -> None:
        '''
        Writes data to Azure Blob storage.

        :param filepath: the full path to the blob
        :param data: the data to be written to the file
        :param file_descriptor: read from the file that the file_descriptor is
        for
        :param file_mode: is the data in the file text or binary
        :param storage_type: use private or public storage account
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

        if data is not None:
            if isinstance(data, str):
                data = data.encode('utf-8')
            file_descriptor = TemporaryFile(mode='w+b')
            file_descriptor.write(data)
            file_descriptor.seek(0)

            if isinstance(data, str):
                data = data.encode('utf-8')
        else:
            # HACK: we should perhaps switch for async I/O to
            # https://pypi.org/project/gcloud-aio-storage/
            data = file_descriptor.read()

        blob = self._get_blob_client(filepath, storage_type)

        # TODO: test case for setting content-type
        if not content_type:
            content_type = FileStorage.get_content_type(filepath)

        with blob.open(f'w{file_mode.value}', content_type=content_type
                       ) as file_desc:
            file_desc.write(data)

        _LOGGER.debug(
            f'Wrote {len(data or [])} bytes for {filepath} to GCP bucket '
            f'{self.buckets[storage_type.value]}'
        )

    async def exists(self, filepath: str,
                     storage_type: StorageType = StorageType.PRIVATE) -> bool:
        '''
        Checks if a file exists on GCP cloud storage

        :param filepath: the key for the object on S3 storage
        :param storage_type: use private or public storage account
        :returns: bool on whether the key exists
        '''

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

    async def delete(self, filepath: str,
                     storage_type: StorageType = StorageType.PRIVATE) -> bool:

        blob = self._get_blob_client(filepath, storage_type)
        blob.delete()

    def get_url(self,  filepath: str = None,
                storage_type: StorageType = StorageType.PRIVATE) -> str:
        '''
        Get the URL for the public storage bucket, ie. something like
        'https://storage.cloud.google.com/<prefix>-[private|public]'

        :param filepath: path to the file
        :param storage_type: return the url for the private or public storage
        :returns: str
        '''

        if filepath is None:
            filepath = ''

        return (
            f'https://{self.domain}/{self.buckets[storage_type.value]}/' +
            filepath
        )

    def get_bucket(self, storage_type: StorageType = StorageType.PRIVATE
                   ) -> str:
        '''
        Get the name of the bucket

        :param storage_type: private, restricted or public storage
        :returns: str
        '''

        return self.domain

    async def create_directory(self, directory: str, exist_ok: bool = True,
                               storage_type: StorageType = StorageType.PRIVATE
                               ) -> bool:
        '''
        Directories do not exist on GCP object storage

        :param directory: location of the file on the file system
        :param exist_ok: do not raise an error if the directory already exists
        :param storage_type: check for the directory on private or public
        storage
        '''

        pass

    async def copy(self, source: str, dest: str,
                   file_mode: FileMode = FileMode.BINARY,
                   storage_type: StorageType = StorageType.PRIVATE,
                   exist_ok: bool = True, content_type: str = None) -> None:
        '''
        Copies a file from the local file system to the Azure storage account

        Note that we only store data in local cache for the private container

        :param source: location of the file on the local file system
        :param dest: key for the S3 object to copy the file to
        :parm file_mode: how the file should be opened
        '''

        data = await super().read(source, file_mode=file_mode)

        blob = self._get_blob_client(dest, storage_type)

        # TODO: test case for setting content-type
        if not content_type:
            content_type = FileStorage.get_content_type(source)

        with blob.open(f'w{file_mode.value}', content_type=content_type
                       ) as file_desc:
            file_desc.write(data)

        _LOGGER.debug(
            f'Uploaded {source} to {dest} on GCP bucket '
        )

        # We populate the local disk cache also with the copy
        if storage_type == StorageType.PRIVATE:
            await super().copy(source, dest)

    async def get_folders(self, folder_path: str, prefix: str = None,
                          storage_type: StorageType = StorageType.PRIVATE
                          ) -> set[str]:
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
                    # GCP appends '/' to folders
                    folders.add(folder.rstrip('/'))

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
