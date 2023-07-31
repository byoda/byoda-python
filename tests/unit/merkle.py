#!/usr/bin/env python3

import os
import sys
# import shutil
import unittest

from pymerkle.proof import InvalidProof
from pymerkle import verify_consistency, verify_inclusion, MerkleProof

from byoda.util.merkletree import AssetMerkleTree
from byoda.util.merkletree import BLOCKSIZE

from byoda.util.logger import Logger

ASSET_DIR: str = 'tests/collateral/video_asset'
TEST_DIR: str = '/tmp/byoda-tests/merkle'


class TestAccountManager(unittest.TestCase):
    def setUp(self):
        # shutil.rmtree(TEST_DIR) if os.path.exists(TEST_DIR) else None

        # shutil.copytree(ASSET_DIR, TEST_DIR)
        pass

    def test_pymerkle(self):
        tree: AssetMerkleTree = AssetMerkleTree.calculate(
            f'{ASSET_DIR}'
        )

        print(f'length: {tree.get_size()}')
        # print(str(tree))

        with self.assertRaises(KeyError):
            id = tree.find(b'fake')

        file_desc = os.open(
            'tests/collateral/local/video_asset/asset5Y9L5NBINV4.139.m4a',
            os.O_RDONLY
        )

        data = os.read(file_desc, BLOCKSIZE)

        id = tree.find(data)
        proof: MerkleProof = tree.prove_inclusion(tree.get_leaf(10))
        with self.assertRaises(InvalidProof):
            pass
            # tree.proof_inclusion(id)
            # verify_inclusion(tree.get_state(), forged.get_state())


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
