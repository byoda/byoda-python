'''
Bring your own algorithm backend storage for the server.

The directory server uses caching storage for server and client registrations
The profile server uses noSQL storage for profile data

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import os
import shutil
import logging
from enum import Enum
from typing import BinaryIO

from byoda.datatypes import CloudType
from byoda.datatypes import StorageType
from byoda.datatypes import ContentTypes

_LOGGER = logging.getLogger(__name__)

PUBLIC_POSTFIX: str = 'public'
RESTRICTED_POSTFIX: str = 'restricted'


class OpenMode(Enum):
    READ     = 'r'          # noqa: E221
    WRITE    = 'w'          # noqa: E221


class FileMode(Enum):
    TEXT     = ''           # noqa: E221
    BINARY   = 'b'          # noqa: E221


class FileStorage:
    '''
    Class that abstracts storing data in object storage while
    keeping a local copy for fast reads.
    '''

    def __init__(self, local_path: str,
                 cloud_type: CloudType = CloudType.LOCAL):

        # These properties are only applicable if this instance
        # is derived from one of the cloud-storage classes
        self.cloud_type: CloudType = cloud_type

        if cloud_type != CloudType.LOCAL:
            if local_path:
                self.local_path: str = '/' + local_path.strip('/') + '/'
            else:
                self.local_path: str = '/tmp/'
        else:
            if not local_path:
                raise ValueError('Must specify local path')

            self.local_path: str = '/' + local_path.strip('/') + '/'

        os.makedirs(self.local_path, exist_ok=True)

        _LOGGER.debug('Initialized file storage under %s', self.local_path)

    @staticmethod
    async def setup(root_dir: str):
        '''
        Factory for FileStorage

        :param root_dir: directory on the local file system under which files
        will be stored
        '''

        return FileStorage(root_dir)

    @staticmethod
    async def get_storage(cloud: CloudType, private_bucket, restricted_bucket,
                          public_bucket, root_dir: str):
        '''
        Factory for FileStorage and classes derived from it

        For GCP, the environment variable
        :param cloud: the cloud that we are looking to use for object
        storage
        :param private_bucket:
        :param restricted_bucket:
        :param public_bucket:
        :param root_dir: the directory on the local file system that
        will be used to cache content
        :returns: instance of FileStorage or a class derived from it
        '''
        if isinstance(cloud, str):
            cloud = CloudType(cloud)

        if cloud == CloudType.AWS:
            from .aws import AwsFileStorage
            storage = await AwsFileStorage.setup(
                private_bucket, restricted_bucket, public_bucket, root_dir)
        elif cloud == CloudType.AZURE:
            from .azure import AzureFileStorage
            storage = await AzureFileStorage.setup(
                private_bucket, restricted_bucket, public_bucket, root_dir
            )
        elif cloud == CloudType.GCP:
            from .gcp import GcpFileStorage
            storage = await GcpFileStorage.setup(
                private_bucket, restricted_bucket, public_bucket, root_dir
            )
        elif cloud == CloudType.LOCAL:
            _LOGGER.debug('Using LOCAL storage')
            storage = await FileStorage.setup(root_dir)
        else:
            raise NotImplementedError(
                f'There is no support for cloud {cloud}'
            )

        _LOGGER.debug(f'Initialized {cloud} storage')

        return storage

    def get_full_path(self, filepath: str, create_dir: bool = True,
                      storage_type: StorageType = StorageType.PRIVATE
                      ) -> tuple[str, str]:
        '''
        Returns the absolute path for the file path relative
        to the local directory

        :param filepath: relative path to the file
        :param create_dir: should an attempt be made to create the directory
        :returns: dirpath (ending in '/'), filename
        '''

        # We mimic k/v store where there are no 'directories' or 'folders'
        # that you have to create
        relative_path, filename = os.path.split(filepath)
        relative_path = relative_path.rstrip('/')

        if storage_type == StorageType.PRIVATE:
            if relative_path.startswith(self.local_path):
                dirpath = relative_path
            else:
                dirpath = self.local_path + relative_path
        elif storage_type == StorageType.RESTRICTED:
            dirpath = (
                self.local_path.rstrip('/') + '/' + RESTRICTED_POSTFIX +
                '/' + relative_path
            )
        else:
            dirpath = (
                self.local_path.rstrip('/') + '/' + PUBLIC_POSTFIX +
                '/' + relative_path
            )

        if create_dir:
            os.makedirs(dirpath, exist_ok=True)

        return dirpath, filename

    def open(self, filepath: str, open_mode: OpenMode = OpenMode.READ,
             file_mode: FileMode = FileMode.BINARY,
             storage_type: StorageType = StorageType.PRIVATE) -> BinaryIO:
        '''
        Open a file on the local file system
        '''

        dirpath, filename = self.get_full_path(filepath, storage_type)

        _LOGGER.debug(f'Opening local file {dirpath}/{filename}')
        return open(
            f'{dirpath}/{filename}', f'{open_mode.value}{file_mode.value}'
        )

    def close(self, file_descriptor: BinaryIO):
        '''
        Closes a file descriptor as returned by self.open()
        '''

        file_descriptor.close()

    async def close_clients(self):
        '''
        Dummy function for Cloud Storage clients like Azure that need their
        async clients to be closed explicitly
        '''

        pass

    async def read(self, filepath: str, file_mode: FileMode = FileMode.BINARY,
                   storage_type: StorageType = StorageType.PRIVATE) -> str:
        '''
        Read a file

        :param filepath: location of the file on the file system
        :param file_mode: read file as text or as binary
        :returns: str or bytes, depending on the file_mode parameter
        '''

        dirpath, filename = self.get_full_path(
            filepath, storage_type=storage_type
        )

        updated_filepath = f'{dirpath}/{filename}'
        openmode = f'r{file_mode.value}'

        with open(updated_filepath, openmode) as file_desc:
            data = file_desc.read()

        _LOGGER.debug(
            f'Read {len(data or [])} bytes from local file {updated_filepath}'
        )

        return data

    async def write(self, filepath: str, data: bytes = None,
                    file_descriptor=None,
                    file_mode: FileMode = FileMode.BINARY,
                    storage_type: StorageType = StorageType.PRIVATE) -> None:
        '''
        Writes a str or bytes to the local file system

        :param filepath: location of the file on the file system
        :param data: the data to be written to the file
        :param file_descriptor: read from the file that the file_descriptor is
        for. The file descriptor must use the text/binary mode
        as specified by the file_mode parameter
        :param file_mode: read file as text or as binary
        '''

        if data is None and file_descriptor is None:
            raise ValueError('Either data or file_descriptor must be provided')

        if data is not None and len(data) > 2 * 1024*1024*1024:
            raise ValueError('Writing data larger than 2GB is not supported')

        if isinstance(data, str) and file_mode == FileMode.BINARY:
            data = data.encode('utf-8')

        dirpath, filename = self.get_full_path(
            filepath, storage_type=storage_type
        )

        os.makedirs(dirpath, exist_ok=True)

        updated_filepath = f'{dirpath}/{filename}'
        openmode = f'w{file_mode.value}'

        if file_descriptor:
            data = file_descriptor.read()

        with open(updated_filepath, openmode) as file_desc:
            file_desc.write(data)

        _LOGGER.debug(
            f'Wrote {len(data or [])} bytes to local file {updated_filepath}'
        )

    def append(self, filepath: str, data: str,
               file_mode: FileMode = FileMode.BINARY,
               storage_type: StorageType = StorageType.PRIVATE):
        '''
        Append data to a file

        :param filepath: location of the file on the file system
        :param data: array of data to write to the file
        :param file_mode: read file as text or as binary
        '''

        dirpath, filename = self.get_full_path(
            filepath, storage_type=storage_type
        )

        with open(dirpath + filename, f'w{file_mode.value}') as file_desc:
            file_desc.write(data)

    async def exists(self, filepath: str,
                     storage_type: StorageType = StorageType.PRIVATE) -> bool:
        '''
        Check if the file exists in the local file system

        :param filepath: location of the file on the file system
        :returns: whether the file exists or not
        '''

        dirpath, filename = self.get_full_path(
            filepath, create_dir=False, storage_type=storage_type
        )

        exists = os.path.exists(f'{dirpath}/{filename}')
        if not exists:
            _LOGGER.debug(
                'File not found in local filesystem: '
                f'{dirpath}/{filename}'
            )
        return exists

    def save(self, filepath: str, data: str,
             file_mode: FileMode = FileMode.BINARY):
        '''
        Saves file to local file system, even when called via a
        cloud storage class derived from this class

        :param filepath: location under the root_dir to save the file
        :param data: data to save to the file
        :param file_mode: write file as text or as binary
        '''

        dirpath, filename = self.get_full_path(filepath)

        with open(dirpath + filename, f'w{file_mode.value}') as file_desc:
            file_desc.write(data)

    async def move(self, src_filepath: str, dest_filepath: str,
                   storage_type: StorageType = StorageType.PRIVATE):
        '''
        Moves the file to the destination file
        :param src_filepath: absolute full path + file name of the source file
        :param dest_filepath: full path + file name of the destination file
        relative to the root directory
        :raises: FileNotFoundError, PermissionError
        '''

        dirpath, filename = self.get_full_path(
            dest_filepath, create_dir=True, storage_type=storage_type)

        shutil.move(src_filepath, dirpath + '/' + filename)

    async def delete(self, filepath: str,
                     storage_type: StorageType = StorageType.PRIVATE) -> bool:
        '''
        Delete the file from the local file system
        :param filepath: location of the file on the file system
        :returns: whether the file exists or not
        '''

        dirpath, filename = self.get_full_path(
            filepath, storage_type=storage_type
        )

        try:
            if filename:
                try:
                    os.remove(dirpath + '/' + filename)
                except IsADirectoryError:
                    shutil.rmtree(dirpath, ignore_errors=True)
            else:
                shutil.rmtree(dirpath, ignore_errors=True)
            return True
        except FileNotFoundError:
            return False

    def get_url(self, filepath: str = None,
                storage_type: StorageType = StorageType.PRIVATE) -> str:
        '''
        Get the URL for the local storage.

        :param filepath: path to the file
        :param storage_type: return the url for the private or public storage
        :returns: str
        '''

        if not filepath:
            filepath = '/'

        bucket = self.get_bucket(storage_type=storage_type)

        filepath = f'{bucket}/{filepath}'

        return filepath

    def get_bucket(self, storage_type: StorageType = StorageType.PRIVATE
                   ) -> str:
        '''
        Get the bucket name for the storage type

        :param storage_type: return the bucket name for the private,
        restricted, or public storage
        :returns: str
        '''

        path = self.local_path
        if storage_type == StorageType.PUBLIC:
            path += PUBLIC_POSTFIX
        elif storage_type == StorageType.RESTRICTED:
            path += RESTRICTED_POSTFIX

        return path

    async def create_directory(self, directory: str, exist_ok: bool = True,
                               storage_type: StorageType = StorageType.PRIVATE
                               ) -> None:
        '''
        Creates a directory on the local file system, including any
        intermediate directories if they don't exist already

        :param filepath: location of the file on the file system
        :param exist_ok: bool on whether to ignore if the directory already
        exists
        '''

        dirpath, filename = self.get_full_path(
            directory, create_dir=False, storage_type=storage_type
        )
        _LOGGER.debug(f'Creating directory: {dirpath}')
        return os.makedirs(dirpath, exist_ok=exist_ok)

    def getmtime(self, filepath: str,
                 storage_type: StorageType = StorageType.PRIVATE) -> float:
        '''
        Returns the last modified time of a file on the local file system

        :param filepath: location of the file on the file system
        :returns: the number of seconds since epoch that the file was modified
        '''

        dirpath, filename = self.get_full_path(
            filepath, create_dir=False, storage_type=storage_type
        )

        return os.stat.getmtime(dirpath + filename)

    async def copy(self, src: str, dest: str,
                   storage_type: StorageType = StorageType.PRIVATE,
                   exist_ok=True) -> None:
        '''
        Copies a file on the local file system
        '''

        dest_dirpath, dest_filename = self.get_full_path(
            dest, storage_type=storage_type
        )

        dest_filepath = dest_dirpath + '/' + dest_filename
        if os.path.exists(dest_filename) and not exist_ok:
            raise FileExistsError(dest_filepath)

        result = shutil.copyfile(src, dest_filepath)

        _LOGGER.debug(
            f'Copied src to '
            f'{dest_dirpath}/{dest_filename} on the local file '
            f'system: {result}'
        )

    async def get_folders(self, folder_path: str, prefix: str = None,
                          storage_type: StorageType = StorageType.PRIVATE
                          ) -> list[str]:
        '''
        Gets the folders/directories for a directory on the a filesystem
        '''

        folders = []

        dir_path = self.get_full_path(
            folder_path, storage_type=storage_type
        )[0]

        for directory in os.listdir(dir_path):
            if not prefix or directory.startswith(prefix):
                if os.path.isdir(os.path.join(dir_path, directory)):
                    folders.append(directory)

        return folders

    @staticmethod
    def get_content_type(filepath) -> str:
        _, file_extension = os.path.splitext(filepath)
        content_type = ContentTypes.get(
            file_extension, 'application/octet-stream'
        )
        return content_type
