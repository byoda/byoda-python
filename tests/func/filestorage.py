#!/usr/bin/env python3

'''
Test the Azure Storage code

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import os
import sys
import requests
import shutil
import unittest
from typing import Type
from byoda.storage.aws import AwsFileStorage
from byoda.storage.azure import AzureFileStorage
from byoda.storage.gcp import GcpFileStorage

from byoda.util.logger import Logger

from byoda.storage import FileStorage
from byoda.datatypes import StorageType, CloudType

ROOT_DIR = '/tmp/byoda-tests/filestorage'


class TestFileStorage(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(ROOT_DIR, ignore_errors=True)
        os.makedirs(ROOT_DIR, exist_ok=True)

    def test_gcp_storage(self):
        storage = FileStorage.get_storage(
            CloudType.GCP, 'byoda', root_dir=ROOT_DIR
        )
        run_file_tests(self, storage)

    def test_azure_storage(self):
        storage = FileStorage.get_storage(
            CloudType.AZURE, 'byoda', root_dir=ROOT_DIR
        )
        run_file_tests(self, storage)

    def test_aws_storage(self):
        storage = FileStorage.get_storage(
            CloudType.AWS, 'byoda', root_dir=ROOT_DIR
        )
        run_file_tests(self, storage)

    def test_local_storage(self):
        storage = FileStorage(ROOT_DIR)
        run_file_tests(self, storage)


def run_file_tests(test: Type[TestFileStorage], storage: FileStorage):

    # Prep the test by putting the file in the directory used by the
    # FileStorage instance
    shutil.copy('/etc/profile', ROOT_DIR + '/profile')

    storage.copy(
        '/profile', 'test/profile',
        storage_type=StorageType.PRIVATE
    )

    with open('/etc/profile', 'rb') as file_desc:
        profile_data = file_desc.read()

    data = storage.read('test/profile')
    test.assertEqual(profile_data, data)

    write_filepath = 'test/subdir/profile-write'
    storage.write(write_filepath, data)
    storage.write('test/anothersubdir/profile-write', data)

    exists = storage.exists(write_filepath)
    test.assertTrue(exists)

    exists = storage.exists('blahblah/blahblah')
    test.assertFalse(exists)

    subdirs = storage.get_folders('test/')
    test.assertEqual(len(subdirs), 2)

    subdirs = storage.get_folders('test/', prefix='sub')
    test.assertEqual(len(subdirs), 1)

    if (type(storage) in
            (AzureFileStorage, AwsFileStorage, GcpFileStorage)):
        url = storage.get_url() + 'test/profile'
        response = requests.get(url, allow_redirects=False)
        test.assertIn(response.status_code, (302, 403, 409))

    storage.delete('test/profile')
    storage.delete('test/anothersubdir/profile-write')
    storage.delete('test/subdir/profile-write')

    # GCP delete also deletes empty parent 'folders'??
    if not type(storage) in (AzureFileStorage, GcpFileStorage):
        storage.delete('test/subdir/')
        storage.delete('test/anothersubdir/')
        storage.delete('test')


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
