#!/usr/bin/env python3

import sys
import yaml
import unittest

from logging import Logger

from byoda.storage.ceph_storage import CephFileStorage

from byoda.util.logger import Logger as ByodaLogger

CONFIG_FILE = 'tests/collateral/local/config_ceph.yml'
CONFIG: dict[str, str] = {}


class TestCeph(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        with open(CONFIG_FILE) as config_file:
            self.config_data: dict = yaml.safe_load(config_file)

    async def test_setup(self) -> None:
        ceph_storage: CephFileStorage = await CephFileStorage.setup(
            private_bucket='my-private-bucket',
            restricted_bucket='my-restricted-bucket',
            public_bucket='my-public-bucket',
            root_dir='/tmp/byoda_test_ceph',
            ceph_endpoint=self.config_data['ceph_endpoint'],
            access_key_id=self.config_data['access_key_id'],
            secret_access_key=self.config_data['secret_access_key']
        )

        self.assertIsInstance(ceph_storage, CephFileStorage)

        data = ceph_storage.driver.list_buckets()
        print(data)


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )

    unittest.main()
