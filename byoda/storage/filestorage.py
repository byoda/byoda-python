'''
Bring your own algorithm backend storage for the server.

The directory server uses caching storage for server and client registrations
The profile server uses noSQL storage for profile data

:maintainer : Steven Hessing (stevenhessing@live.com)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import os
import shutil
import logging
from enum import Enum

from byoda.datatypes import CloudType

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

    def __init__(self, local_path: str, bucket: str = None):
        if not local_path:
            self.local_path = '/tmp/'
        else:
            self.local_path = local_path.rstrip('/') + '/'

        _LOGGER.debug('Initialized file storage under %s', self.local_path)
        self.bucket = bucket

    @staticmethod
    def get_storage(cloud: CloudType, bucket: str, root_dir=str):
        '''
        Factor for FileStorage and classes derived from it

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
            storage = AwsFileStorage(bucket, root_dir)
        else:
            storage = FileStorage(root_dir)

        return storage

    def open(self, filepath: str, open_mode: OpenMode = OpenMode.READ,
             file_mode: FileMode = FileMode.TEXT):
        '''
        Open a file on the local file system
        '''

        # First we need to make sure the path in the local file system
        # exists
        path, filename = os.path.split(filepath)
        self.create_directory(path, exist_ok=True)

        _LOGGER.debug('Opening local file %s', filepath)
        return open(filepath, f'{open_mode.value}{file_mode.value}')

    def close(self, file_descriptor):
        '''
        Closes a file descriptor as returned by self.open()
        '''

        file_descriptor.close()

    def read(self, filepath: str, file_mode: FileMode = FileMode.TEXT) -> str:
        '''
        Read a file

        :param filepath: location of the file on the file system
        :param file_mode: read file as text or as binary
        :returns: str or bytes, depending on the file_mode parameter
        '''
        _LOGGER.debug('Reading local file %s', filepath)
        with open(filepath, f'r{file_mode.value}') as file_desc:
            data = file_desc.read()

        return data

    def write(self, filepath: str, data: str,
              file_mode: FileMode = FileMode.TEXT) -> None:
        '''
        Writes a str or bytes to the local file system

        :param filepath: location of the file on the file system
        :param file_mode: read file as text or as binary
        '''
        with open(filepath, f'w{file_mode.value}') as file_desc:
            file_desc.write(data)

    def append(self, filepath: str, data: str,
               file_mode: FileMode = FileMode.TEXT):
        '''
        Append data to a file

        :param filepath: location of the file on the file system
        :param data: array of data to write to the file
        :param file_mode: read file as text or as binary
        '''
        with open(filepath, f'w{file_mode.value}') as file_desc:
            file_desc.write(data)

    def exists(self, filepath: str) -> bool:
        '''
        Check if the file exists in the local file system

        :param filepath: location of the file on the file system
        :returns: whether the file exists or not
        '''
        exists = os.path.exists(filepath)
        if not exists:
            _LOGGER.debug('File not found in local filesystem: %s', filepath)
        return exists

    def create_directory(self, directory: str, exist_ok: bool = True) -> None:
        '''
        Creates a directory on the local file system, including any
        intermediate directories if they don't exist already

        :param filepath: location of the file on the file system
        :param exist_ok: bool on whether to ignore if the directory already
        exists
        '''

        return os.makedirs(directory, exist_ok=True)

    def getmtime(self, filepath: str) -> float:
        '''
        Returns the last modified time of a file on the local file system

        :param filepath: location of the file on the file system
        :returns: the number of seconds since epoch that the file was modified
        '''
        return os.stat.getmtime(filepath)

    def delete(self, filepath: str) -> None:
        return os.remove(filepath)

    def copy(self, source: str, dest: str) -> str:
        '''
        Copies a file on the local file system

        :returns: path to the destination file
        '''
        result = shutil.copy(source, dest)

        _LOGGER.debug(
            'Copied %s to %s on the local file system', source, result
        )

        return result
