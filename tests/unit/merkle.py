#!/usr/bin/env python3

import os
import sys
import base64
import shutil
import unittest

from byoda.util.merkletree import ByoMerkleTree
from byoda.util.merkletree import BLOCKSIZE

from byoda.util.logger import Logger

ASSET_DIR: str = 'tests/collateral/local/video_asset'
TEST_DIR: str = '/tmp/byoda-tests/merkle'


class TestAccountManager(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TEST_DIR) if os.path.exists(TEST_DIR) else None
        os.makedirs(TEST_DIR, exist_ok=True)

    def test_pymerkle(self):
        original_tree: ByoMerkleTree = ByoMerkleTree.calculate(
            f'{ASSET_DIR}'
        )

        self.assertEqual(
            original_tree.root.digest.hex(),
            'df782829b56590a3b4a3ac0f6cb8e626b6bbd0f307b7bb08474482abe3932fdd'
        )
        self.assertEqual(original_tree.get_size(), 641)
        original_tree.save(TEST_DIR)

        with self.assertRaises(KeyError):
            original_tree.find(b'fake')

        file_desc = os.open(
            'tests/collateral/local/video_asset/asset5Y9L5NBINV4.139.m4a',
            os.O_RDONLY
        )
        data = os.read(file_desc, BLOCKSIZE)
        node = original_tree.find(data)
        self.assertEqual(
            node.digest.hex(),
            '07f60df4acf2900089dd30ef20feb4320de359bf645d376a42dbfad27ae9019f'
        )

        new_tree = ByoMerkleTree.load_from_file(TEST_DIR)
        self.assertEqual(original_tree.root.digest, new_tree.root.digest)
        self.assertEqual(original_tree.get_size(), new_tree.get_size())

        self.assertEqual(original_tree.get_state(), new_tree.root.digest)
        self.assertEqual(
            original_tree.as_string(),
            base64.b64encode(new_tree.root.digest).decode('utf-8')
        )


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
