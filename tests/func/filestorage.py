#!/usr/bin/env python3

'''
Test the Azure Storage code

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

TODO: include instructions on how to set up credentials to the AWS, Azure and
GCP clouds so this test case can use those credentials

For Azure, run:
  az login --use-device-code

For Google Cloud run:
  gcloud auth login
  gcloud config set project <project>

For AWS, create a ~/.aws/credentias file with as contents:
  [default]
  aws_access_key_id = <your-access-key-id>
  aws_secret_access_key = <your-secret-access-key>

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import os
import sys
import httpx
import shutil
import unittest

from logging import Logger

from byoda.storage.aws import AwsFileStorage
from byoda.storage.azure import AzureFileStorage
from byoda.storage.gcp import GcpFileStorage

from byoda.storage import FileStorage
from byoda.datatypes import StorageType
from byoda.datatypes import CloudType

from byoda.util.logger import Logger as ByodaLogger

from tests.lib.defines import AZURE_RESTRICTED_BUCKET_FILE
from tests.lib.defines import GCP_RESTRICTED_BUCKET_FILE
from tests.lib.defines import AWS_RESTRICTED_BUCKET_FILE

ROOT_DIR = '/tmp/byoda-tests/filestorage'
CLOUD_STORAGE_TYPES = (AzureFileStorage, AwsFileStorage, GcpFileStorage)


class TestFileStorage(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        shutil.rmtree(ROOT_DIR, ignore_errors=True)
        os.makedirs(ROOT_DIR, exist_ok=True)

    async def test_gcp_storage(self):
        with open(GCP_RESTRICTED_BUCKET_FILE) as file_desc:
            restricted_bucket = file_desc.read().strip()
        storage = await FileStorage.get_storage(
            CloudType.GCP, 'byoda-private', restricted_bucket,
            'byoda-public', ROOT_DIR
        )
        await run_file_tests(self, storage)

        bucket = storage.get_bucket(StorageType.RESTRICTED)
        self.assertEqual(bucket, restricted_bucket)

        bucket = storage.get_bucket(StorageType.PUBLIC)
        self.assertEqual(bucket, 'byoda-public')

    async def test_azure_storage(self) -> None:
        with open(AZURE_RESTRICTED_BUCKET_FILE) as file_desc:
            restricted_bucket = file_desc.read().strip()
        storage = await FileStorage.get_storage(
            CloudType.AZURE, 'byodaprivate:byoda',
            restricted_bucket, 'byodaprivate:public', ROOT_DIR
        )
        await run_file_tests(self, storage)

        bucket = storage.get_bucket(StorageType.RESTRICTED)
        self.assertEqual(bucket, 'byodaprivate.blob.core.windows.net')

        bucket = storage.get_bucket(StorageType.PUBLIC)
        self.assertEqual(bucket, 'byodaprivate.blob.core.windows.net')

    async def test_aws_storage(self):
        with open(AWS_RESTRICTED_BUCKET_FILE) as file_desc:
            restricted_bucket = file_desc.read().strip()
        storage = await FileStorage.get_storage(
            CloudType.AWS, 'byoda-private', restricted_bucket,
            'byoda-public', ROOT_DIR
        )
        await run_file_tests(self, storage)

        bucket = storage.get_bucket(StorageType.RESTRICTED)
        self.assertEqual(
            bucket, f'{restricted_bucket}.s3-us-east-2.amazonaws.com'
        )

        bucket = storage.get_bucket(StorageType.PUBLIC)
        self.assertEqual(
            bucket, 'byoda-public.s3-us-east-2.amazonaws.com'
        )

    async def test_local_storage(self):
        storage = FileStorage(ROOT_DIR)
        await run_file_tests(self, storage)


async def run_file_tests(test: type[TestFileStorage], storage: FileStorage):

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

    subdirs: list[str] = await storage.get_folders('test/')
    test.assertEqual(len(subdirs), 2)

    subdirs = await storage.get_folders('test/', prefix='sub')
    test.assertEqual(len(subdirs), 1)

    if type(storage) in CLOUD_STORAGE_TYPES:
        url: str = storage.get_url(StorageType.PRIVATE) + 'test/profile'

        # This fails because anonymous access to private storage is
        # not allowed
        response = httpx.get(url, allow_redirects=False)
        test.assertIn(response.status_code, (302, 403, 404, 409))

        with open('/bin/ls', 'rb') as file_desc:
            await storage.write(
                'test/file_descriptor_write', file_descriptor=file_desc,
                storage_type=StorageType.PUBLIC
            )

        await storage.delete(
            'test/file_descriptor_write', storage_type=StorageType.PUBLIC
        )

        # Now test public and restricted storage
        asset_id: str = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        filename: str = f'{asset_id}/profile'
        for storage_type in (StorageType.PUBLIC, StorageType.RESTRICTED):
            await storage.copy(
                '/profile', filename, storage_type=storage_type
            )
            test.assertTrue(
                await storage.exists(filename, storage_type=storage_type)
            )
            await storage.delete(filename, storage_type=storage_type)

    await storage.delete('test/profile')
    await storage.delete('test/anothersubdir/profile-write')
    await storage.delete('test/subdir/profile-write')

    # GCP delete also deletes empty parent 'folders'??
    if type(storage) not in (AzureFileStorage, GcpFileStorage):
        await storage.delete('test/subdir/')
        await storage.delete('test/anothersubdir/')
        await storage.delete('test')

    await storage.close_clients()


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
