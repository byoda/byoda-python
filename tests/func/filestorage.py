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
CLOUD_STORAGE_TYPES = (AzureFileStorage, AwsFileStorage, GcpFileStorage)


class TestFileStorage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        shutil.rmtree(ROOT_DIR, ignore_errors=True)
        os.makedirs(ROOT_DIR, exist_ok=True)

    async def test_gcp_storage(self):
        storage = await FileStorage.get_storage(
            CloudType.GCP, 'byoda', root_dir=ROOT_DIR
        )
        await run_file_tests(self, storage)

    async def test_azure_storage(self):
        storage = await FileStorage.get_storage(
            CloudType.AZURE, 'byoda', root_dir=ROOT_DIR
        )
        await run_file_tests(self, storage)

    async def test_aws_storage(self):
        storage = await FileStorage.get_storage(
            CloudType.AWS, 'byoda', root_dir=ROOT_DIR
        )
        await run_file_tests(self, storage)

    async def test_local_storage(self):
        storage = FileStorage(ROOT_DIR)
        await run_file_tests(self, storage)


async def run_file_tests(test: Type[TestFileStorage], storage: FileStorage):

    # Prep the test by putting the file in the directory used by the
    # FileStorage instance
    shutil.copy('/etc/profile', ROOT_DIR + '/profile')

    await storage.copy(
        '/profile', 'test/profile',
        storage_type=StorageType.PRIVATE
    )

    with open('/etc/profile', 'rb') as file_desc:
        profile_data = file_desc.read()

    data = await storage.read('test/profile')
    test.assertEqual(profile_data, data)

    write_filepath = 'test/subdir/profile-write'
    await storage.write(write_filepath, data)
    await storage.write('test/anothersubdir/profile-write', data)

    exists = await storage.exists(write_filepath)
    test.assertTrue(exists)

    exists = await storage.exists('blahblah/blahblah')
    test.assertFalse(exists)

    subdirs = await storage.get_folders('test/')
    test.assertEqual(len(subdirs), 2)

    subdirs = await storage.get_folders('test/', prefix='sub')
    test.assertEqual(len(subdirs), 1)

    if type(storage) in CLOUD_STORAGE_TYPES:
        url = storage.get_url() + 'test/profile'
        response = requests.get(url, allow_redirects=False)
        test.assertIn(response.status_code, (302, 403, 409))

        with open('/bin/ls', 'rb') as file_desc:
            await storage.write(
                'test/file_descriptor_write', file_descriptor=file_desc,
                storage_type=StorageType.PUBLIC
            )

        await storage.delete(
            'test/file_descriptor_write', storage_type=StorageType.PUBLIC
        )

    await storage.delete('test/profile')
    await storage.delete('test/anothersubdir/profile-write')
    await storage.delete('test/subdir/profile-write')

    # GCP delete also deletes empty parent 'folders'??
    if not type(storage) in (AzureFileStorage, GcpFileStorage):
        await storage.delete('test/subdir/')
        await storage.delete('test/anothersubdir/')
        await storage.delete('test')

    await storage.close_clients()


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
