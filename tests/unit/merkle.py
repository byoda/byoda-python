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
            'b48c173c27429bdf1502accffc844808a9b3122a9889478f47a59785e1856e32'
        )
        self.assertEqual(original_tree.get_size(), 65)
        original_tree.save(TEST_DIR)

        with self.assertRaises(KeyError):
            original_tree.find(b'fake')

        file_desc: int = os.open(
            'tests/collateral/local/video_asset/assetU7eAB3gbjic.139.m4a',
            os.O_RDONLY
        )
        data: bytes = os.read(file_desc, BLOCKSIZE)
        node = original_tree.find(data)
        self.assertEqual(
            node.digest.hex(),
            '8d5e3b3ccb8abfecdce3ec71ccc740ad0152874c8bafb6658154333a726c154a'
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
