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
from typing import List, Tuple, BinaryIO

from byoda.datatypes import CloudType, StorageType

_LOGGER = logging.getLogger(__name__)


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
        self.cache_enabled = None
        self.cache_path = None
        self.cloud_type: CloudType = cloud_type

        if cloud_type != CloudType.LOCAL:
            if local_path:
                self.cache_enabled = True
                self.local_path: str = '/' + local_path.strip('/') + '/'
                self.cache_path = self.local_path

            else:
                self.cache_enabled: bool = False
                self.local_path: str = '/tmp/'

            for filename in os.listdir(self.cache_path):
                filepath = os.path.join(self.cache_path, filename)
                if os.path.isdir(filepath):
                    shutil.rmtree(filepath)

        else:
            if not local_path:
                raise ValueError('Must specify local path')

            self.local_path: str = '/' + local_path.strip('/') + '/'

        os.makedirs(self.local_path, exist_ok=True)

        _LOGGER.debug('Initialized file storage under %s', self.local_path)

    @staticmethod
    def get_storage(cloud: CloudType, bucket_prefix: str, root_dir: str = None
                    ):
        '''
        Factory for FileStorage and classes derived from it

        For GCP, the environment variable
        :param cloud: the cloud that we are looking to use for object
        storage
        :param bucket: the bucket storing the data
        :param root_dir: the directory on the local file system that
        will be used to cache content
        :returns: instance of FileStorage or a class derived from it
        '''
        if isinstance(cloud, str):
            cloud = CloudType(cloud)

        if cloud == CloudType.AWS:
            from .aws import AwsFileStorage
            storage = AwsFileStorage(bucket_prefix, root_dir)
        elif cloud == CloudType.AZURE:
            from .azure import AzureFileStorage
            storage = AzureFileStorage(bucket_prefix, root_dir)
        elif cloud == CloudType.GCP:
            from .gcp import GcpFileStorage
            storage = GcpFileStorage(bucket_prefix, root_dir)
        elif cloud == CloudType.LOCAL:
            _LOGGER.debug('Using LOCAL storage')
            storage = FileStorage(root_dir)
        else:
            raise NotImplementedError(
                f'There is no support for cloud {cloud}'
            )

        _LOGGER.debug(f'Initialized {cloud} storage')

        return storage

    def get_full_path(self, filepath: str, create_dir: bool = True
                      ) -> Tuple[str, str]:
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

        dirpath = self.local_path + relative_path

        if create_dir:
            os.makedirs(dirpath, exist_ok=True)

        return dirpath, filename

    def open(self, filepath: str, open_mode: OpenMode = OpenMode.READ,
             file_mode: FileMode = FileMode.BINARY) -> BinaryIO:
        '''
        Open a file on the local file system
        '''

        dirpath, filename = self.get_full_path(filepath)

        _LOGGER.debug(f'Opening local file {dirpath}/{filename}')
        return open(
            f'{dirpath}/{filename}', f'{open_mode.value}{file_mode.value}'
        )

    def close(self, file_descriptor: BinaryIO):
        '''
        Closes a file descriptor as returned by self.open()
        '''

        file_descriptor.close()

    def read(self, filepath: str, file_mode: FileMode = FileMode.BINARY
             ) -> str:
        '''
        Read a file

        :param filepath: location of the file on the file system
        :param file_mode: read file as text or as binary
        :returns: str or bytes, depending on the file_mode parameter
        '''

        dirpath, filename = self.get_full_path(filepath)

        updated_filepath = f'{dirpath}/{filename}'
        openmode = f'r{file_mode.value}'

        _LOGGER.debug(f'Reading local file {updated_filepath}')
        with open(updated_filepath, openmode) as file_desc:
            data = file_desc.read()

        return data

    def write(self, filepath: str, data: bytes,
              file_mode: FileMode = FileMode.BINARY) -> None:
        '''
        Writes a str or bytes to the local file system

        :param filepath: location of the file on the file system
        :param file_mode: read file as text or as binary
        '''

        if isinstance(data, str) and file_mode == FileMode.BINARY:
            data = data.encode('utf-8')

        dirpath, filename = self.get_full_path(filepath)

        updated_filepath = f'{dirpath}/{filename}'
        openmode = f'w{file_mode.value}'

        _LOGGER.debug(f'Writing local file {updated_filepath}')
        with open(updated_filepath, openmode) as file_desc:
            file_desc.write(data)

    def append(self, filepath: str, data: str,
               file_mode: FileMode = FileMode.BINARY):
        '''
        Append data to a file

        :param filepath: location of the file on the file system
        :param data: array of data to write to the file
        :param file_mode: read file as text or as binary
        '''

        dirpath, filename = self.get_full_path(filepath)

        with open(dirpath + filename, f'w{file_mode.value}') as file_desc:
            file_desc.write(data)

    def exists(self, filepath: str) -> bool:
        '''
        Check if the file exists in the local file system

        :param filepath: location of the file on the file system
        :returns: whether the file exists or not
        '''

        dirpath, filename = self.get_full_path(filepath, create_dir=False)

        exists = os.path.exists(f'{dirpath}/{filename}')
        if not exists:
            _LOGGER.debug(
                f'File not found in local filesystem: {dirpath}/{filename}'
            )
        return exists

    def move(self, src_filepath: str, dest_filepath: str):
        '''
        Moves the file to the destination file
        :param src_filepath: absolute full path + file name of the source file
        :param dest_filepath: full path + file name of the destination file relative
        to the root directory
        :raises: FileNotFoundError, PermissionError
        '''

        dirpath, filename = self.get_full_path(dest_filepath, create_dir=False)

        shutil.move(src_filepath, dirpath + filename)

    def delete(self, filepath: str) -> bool:
        '''
        Delete the file from the local file system
        :param filepath: location of the file on the file system
        :returns: whether the file exists or not
        '''

        dirpath, filename = self.get_full_path(filepath)
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

    def get_url(self, public: bool = True) -> str:
        '''
        Get the URL for the public storage bucket. With local storage,
        which should only be used for testing, we assume that there
        is a web server running on 'localhost'
        '''

        return 'http://localhost'

    def create_directory(self, directory: str, exist_ok: bool = True) -> None:
        '''
        Creates a directory on the local file system, including any
        intermediate directories if they don't exist already

        :param filepath: location of the file on the file system
        :param exist_ok: bool on whether to ignore if the directory already
        exists
        '''

        dirpath, filename = self.get_full_path(directory, create_dir=False)
        return os.makedirs(dirpath, exist_ok=True)

    def getmtime(self, filepath: str) -> float:
        '''
        Returns the last modified time of a file on the local file system

        :param filepath: location of the file on the file system
        :returns: the number of seconds since epoch that the file was modified
        '''

        dirpath, filename = self.get_full_path(filepath)
        return os.stat.getmtime(dirpath + filename)

    def copy(self, src: str, dest: str,
             storage_type: StorageType = StorageType.PRIVATE) -> None:
        '''
        Copies a file on the local file system
        '''
        src_dirpath, src_filename = self.get_full_path(src)
        dest_dirpath, dest_filename = self.get_full_path(dest)

        result = shutil.copyfile(
            src_dirpath + src_filename, dest_dirpath + '/' + dest_filename
        )

        _LOGGER.debug(
            f'Copied {src_dirpath}{src_filename} to '
            f'{dest_dirpath}{dest_filename} on the local file system: {result}'
        )

    def get_folders(self, folder_path: str, prefix: str = None) -> List[str]:
        '''
        Gets the folders/directories for a directory on the a filesystem
        '''
        folders = []

        dir_path = self.get_full_path(folder_path)[0]

        for directory in os.listdir(dir_path):
            if not prefix or directory.startswith(prefix):
                if os.path.isdir(os.path.join(dir_path, directory)):
                    folders.append(directory)

        return folders
