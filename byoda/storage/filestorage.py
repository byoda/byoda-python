'''
Bring your own algorithm backend storage for the server.

The directory server uses caching storage for server and client registrations
The profile server uses noSQL storage for profile data

:maintainer : Steven Hessing (stevenhessing@live.com)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import os
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

        storage = FileStorage(root_dir)

        return storage

    def open(self, filepath, open_mode=OpenMode.READ, file_mode=FileMode.TEXT):
        return open(filepath, f'{open_mode.value}{file_mode.value}')

    def read(self, filepath, file_mode=FileMode.TEXT):
        with open(filepath, f'r{file_mode.value}') as file_desc:
            data = file_desc.read()

        return data

    def write(self, filepath, data, file_mode=FileMode.TEXT):
        with open(filepath, f'w{file_mode.value}') as file_desc:
            file_desc.write(data)

    def append(self, filepath, data, file_mode=FileMode.TEXT):
        with open(filepath, f'w{file_mode.value}') as file_desc:
            file_desc.write(data)

    def exists(self, filepath):
        exists = os.path.exists(filepath)
        if not exists:
            _LOGGER.debug('File not found: %s', filepath)
        return exists
        
    def getmtime(self, filepath):
        return os.stat.getmtime(filepath)

    def delete(self, filepath):
        raise os.remove(filepath)
