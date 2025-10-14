'''
Merkle tree manipulation utilities

For an asset folder containing a number of files, a 'file.manifest' file
be created containing for each file the name of the file and the merkle tree
hash of that file. The sh256 has of the manifest file is available to store
in the membership db

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023, 2024, 2025
:license    : GPLv3
'''

import os
import base64

from typing import Self
from typing import Literal
from logging import Logger
from logging import getLogger

import orjson

from pymerkle import BaseMerkleTree
from pymerkle.utils import decompose

from pymerkle.hasher import MerkleHasher

_LOGGER: Logger = getLogger(__name__)

BLOCKSIZE: int = 1024 * 1024

JSON_LEAF_DIGESTS_KEY: str = 'leaf_digests'

MERKLE_FILENAME: str = 'merkle-tree.json'


class Node:
    '''
    Merkle-tree node.

    :param digest: hash value to be stored
    :type digest: bytes
    :param left: [optional] left child
    :type left: Node
    :param right: [optional] right child
    :type right: Node
    :rtype: Node
    '''

    __slots__ = ('digest', 'left', 'right', 'parent')

    def __init__(self, digest: bytes, left=None, right=None):
        self.digest = digest

        self.left = left
        if left:
            left.parent = self

        self.right = right
        if right:
            right.parent = self

        self.parent = None

    def is_root(self) -> bool:
        '''
        Returns *True* iff the node is currently root.
        '''

        return not self.parent

    def is_leaf(self) -> bool:
        '''
        Returns *True* iff the node is leaf.
        '''

        return not self.left and not self.right

    def is_left_child(self) -> bool:
        '''
        Returns *True* iff the node is currently left child.
        '''

        parent = self.parent
        if not parent:
            return False

        return self == parent.left

    def is_right_child(self) -> bool:
        '''
        Returns *True* iff the node is currently right child.
        '''

        parent = self.parent
        if not parent:
            return False

        return self == parent.right

    def get_ancestor(self, degree: int) -> Self:
        '''
        .. note:: Ancestor of degree 0 is the node itself, ancestor of degree
            1 is the node's parent, etc.

        :rtype: Node
        '''

        curr: Self = self
        while degree > 0:
            curr = curr.parent
            degree -= 1

        return curr

    def expand(self, indent: int = 2, trim: int | None = None, level: int = 0,
               ignored: list[str] = None) -> str:
        '''
        Returns a string representing the subtree rooted at the present node.

        :param indent: [optional]
        :param trim: [optional]
        :param level: [optional]
        :param ignored: [optional]
        '''

        ignored = ignored or []

        out: str
        if level == 0:
            out = 2 * '\n' + ' └─' if not self.parent else ''
        else:
            out = (indent + 1) * ' '

        col = 1
        while col < level:
            out += ' │' if col not in ignored else 2 * ' '
            out += indent * ' '
            col += 1

        if self.is_left_child():
            out += ' ├──'

        if self.is_right_child():
            out += ' └──'
            ignored += [level]

        checksum: str = self.digest.hex()
        out += (checksum[:trim] + '...') if trim else checksum
        out += '\n'

        if self.is_leaf():
            return out

        recursion: tuple[int, int | None, int, list[str]] = \
            (indent, trim, level + 1, ignored[:])

        out += self.left.expand(*recursion)
        out += self.right.expand(*recursion)

        return out


class ByoMerkleTree(BaseMerkleTree):
    def __init__(self, directory: str = None, algorithm: str = 'sha256',
                 **opts) -> None:
        '''
        Initializes the merkle tree for the asset folder
        '''
        self.directory: str = directory
        self.filepath: str = \
            f'{self.directory}/{MERKLE_FILENAME}'

        self.root = None
        self.leaves: list = []

        super().__init__(algorithm, **opts)

    def __str__(self, indent=2, trim=8) -> str:
        '''
        :returns: visual representation of the tree
        :rtype: str
        '''
        if not self.root:
            return '\n └─[None]\n'

        return self.root.expand(indent, trim) + '\n'

    def as_string(self, state: int = None) -> str:
        return base64.b64encode(self.get_state(state)).decode('utf-8')

    def _encode_entry(self, data: bytes) -> bytes:
        '''
        Returns the binary format of the provided data entry.

        :param data: data to encode
        '''

        return data

    def _store_leaf(self, data: bytes, digest: bytes) -> int:
        '''
        Creates a new leaf storing the provided data entry along with
        its hash value.

        :param data: data entry
        :param digest: hashed data
        :returns: index of newly appended leaf counting from one
        '''

        tail = Node(digest)

        if not self.leaves:
            self.leaves += [tail]
            self.root = tail
            return 1

        node = self._get_last_maximal_subroot()
        self.leaves += [tail]

        digest = self._hash_nodes(node.digest, tail.digest)
        if node.is_root():
            self.root = Node(digest, node, tail)
            index: int = self._get_size()
            return index

        curr = node.parent
        curr.right = Node(digest, node, tail)
        curr.right.parent = curr
        while curr:
            curr.digest = self._hash_nodes(
                curr.left.digest, curr.right.digest)
            curr = curr.parent

        index = self._get_size()
        return index

    def _get_leaf(self, index: int) -> bytes:
        '''
        Returns the hash stored at the specified leaf.

        :param index: leaf index counting from one
        '''

        if index < 1 or index > len(self.leaves):
            raise ValueError("%d not in leaf range" % index)

        return self.leaves[index - 1].digest

    def _get_leaves(self, offset: int, width: int) -> list[bytes]:
        '''
        Returns in respective order the hashes stored by the leaves in the
        specified range.

        :param offset: starting position counting from zero
        :param width: number of leaves to consider
        '''

        return [
            leaf.digest for leaf in self.leaves[offset: offset + width]
        ]

    def _get_size(self) -> int:
        '''
        :returns: current number of leaves
        :rtype: int
        '''
        return len(self.leaves)

    @classmethod
    def init_from_entries(cls, entries: list[bytes], algorithm: str = 'sha256',
                          **opts) -> Self:
        '''
        Create tree from initial data

        :param entries: initial data to append
        :param algorithm: [optional] hash function. Defaults to *sha256*
        '''
        tree: Self = cls(algorithm, **opts)

        append_entry: callable = tree.append_entry
        for data in entries:
            append_entry(data)

        return tree

    def get_state(self, size: int = None) -> bytes:
        '''
        Computes the root-hash of the subtree corresponding to the provided
        size

        .. note:: Overrides the function inherited from the base class.

        :param size: [optional] number of leaves to consider. Defaults to
            current tree size.
        '''

        currsize: int = self._get_size()

        if size is None:
            size = currsize

        if size == 0:
            return self.hash_empty()

        if size == currsize:
            return self.root.digest

        subroots = self._get_subroots(size)
        result = subroots[0].digest
        i = 0
        while i < len(subroots) - 1:
            result = self._hash_nodes(subroots[i + 1].digest, result)
            i += 1

        return result

    def _inclusion_path_fallback(self, offset: int
                                 ) -> tuple[list[int], list[bytes]]:
        '''
        Non-recursive utility using concrete traversals to compute the
        inclusion path against the current number of leaves.

        :param offset: base leaf index counting from zero
        '''

        base = self.leaves[offset]
        bit: Literal[1] | Literal[0] = 1 if base.is_right_child() else 0

        path: list = [base.digest]
        rule: list[Literal[0] | Literal[1]] = [bit]

        curr = base
        while curr.parent:
            parent = curr.parent

            if curr.is_left_child():
                digest = parent.right.digest
                bit = 0 if parent.is_left_child() else 1
            else:
                digest = parent.left.digest
                bit = 1 if parent.is_right_child() else 0

            rule += [bit]
            path += [digest]
            curr = parent

        # Last bit is insignificant; fix it to zero just to be fully compatible
        # with the output of the overriden method
        rule[-1] = 0

        return rule, path

    def _inclusion_path(self, start: int, offset: int, limit: int, bit: int
                        ) -> tuple[list[int], list[bytes]]:
        '''
        Computes the inclusion path for the leaf located at the provided offset
        against the specified leaf range

        .. warning:: This is an unoptimized recursive function intended for
        reference and testing. Use ``_inclusion_path`` in production.

        :param start: leftmost leaf index counting from zero
        :param offset: base leaf index counting from zero
        :param limit: rightmost leaf index counting from zero
        :param bit: indicates direction during path parenthetization
        '''

        if start == 0 and limit == self._get_size():
            return self._inclusion_path_fallback(offset)

        return super()._inclusion_path(start, offset, limit, bit)

    def _get_subroot_node(self, index: int, height: int):
        '''
        Returns the root node of the perfect subtree of the provided height
        whose leftmost leaf node is located at the provided position.

        .. note:: Returns *None* if no binary subtree exists for the provided
            parameters.

        :param index: position of leftmost leaf node coutning from one
        :param height: height of requested subtree
        :rtype: Node
        '''

        node = self.leaves[index - 1]

        if not node:
            return

        i = 0
        while i < height:
            curr = node.parent

            if not curr:
                return

            if curr.left is not node:
                return

            node = curr
            i += 1

        # Verify existence of perfect subtree rooted at the detected node
        curr = node
        i = 0
        while i < height:
            if curr.is_leaf():
                return

            curr = curr.right
            i += 1

        return node

    def _get_last_maximal_subroot(self):

        '''
        Returns the root node of the perfect subtree of maximum possible size
        containing the currently last leaf.

        :rtype: Node
        '''

        degree = decompose(len(self.leaves))[0]

        return self.leaves[-1].get_ancestor(degree)

    def _get_subroots(self, size: int) -> list:
        '''
        Returns in respective order the root nodes of the successive perfect
        subtrees whose sizes sum up to the provided size.

        :param size:
        :rtype: list[Node]
        '''

        if size < 0 or size > self._get_size():
            return []

        subroots: list = []
        offset = 0
        for height in reversed(decompose(size)):
            node = self._get_subroot_node(offset + 1, height)

            if not node:
                return []

            subroots += [node]
            offset += 1 << height

        return list(reversed(subroots))

    def append_entry_by_digest(self, digest: bytes) -> int:
        '''
        Append a leaf node to the merkle tree by digest

        :param digest: digest of the data to append
        '''

        index: int = self._store_leaf(None, digest)

        return index

    def digests_as_json(self) -> str:
        '''
        Returns the json representation of the digests of the leaves of the
        tree.
        '''

        data: dict[str, list[str]] = {
            JSON_LEAF_DIGESTS_KEY: [
                base64.b64encode(leaf.digest).decode('utf-8')
                for leaf in self.leaves
            ]
        }
        return orjson.dumps(data, option=orjson.OPT_INDENT_2).decode('utf-8')

    @staticmethod
    def load_from_file(directory: str, filename: str = MERKLE_FILENAME
                       ) -> Self:
        '''
        Factory for ByoMerkleTree, populating the tree with the digests
        read from a file

        :param directory:
        :param filename:
        '''

        filepath: str = f'{directory}/{filename}'

        _LOGGER.debug(f'Reading merkle leaf digests from {filepath}')
        with open(filepath, 'r') as file_desc:
            text: str = file_desc.read()

        data: list[str] = orjson.loads(text)

        if JSON_LEAF_DIGESTS_KEY not in data:
            raise ValueError(f'No leaf digests found in {filepath}')

        leafs: list[bytes] = [
            base64.b64decode(digest) for digest in data[JSON_LEAF_DIGESTS_KEY]
        ]
        tree: ByoMerkleTree = ByoMerkleTree.from_digests(leafs)

        return tree

    @staticmethod
    def from_digests(digests: list[bytes], algorithm: str = 'sha256') -> Self:
        '''
        Factory for a Merkle tree generated from a list of digests instead
        of from files

        :param digests:
        :param algorithm:
        '''

        tree = ByoMerkleTree(algorithm=algorithm)
        for digest in digests:
            tree.append_entry_by_digest(digest)

        return tree

    def save(self, directory: str, filename: str = MERKLE_FILENAME) -> str:
        '''
        Save the digests of the leaf nodes to a JSON file

        :param filepath: full path to the file to save
        :returns: name of the saved file, without any path
        :raises: IOError
        '''

        text: str = self.digests_as_json()
        filepath: str = f'{directory}/{filename}'

        _LOGGER.debug(f'Writing merkle leaf digests to {filepath}')
        with open(filepath, 'w') as file_desc:
            file_desc.write(text)

        return filename

    @staticmethod
    def calculate(directory: str, blocksize: int = BLOCKSIZE,
                  algorithm: str = 'sha256') -> Self:
        tree = ByoMerkleTree(directory, algorithm=algorithm)
        _LOGGER.debug(
            f'Creating merkle tree from files in direcory {directory}'
        )
        for file in sorted(os.listdir(tree.directory)):
            if file == MERKLE_FILENAME:
                continue

            filepath: str = f'{tree.directory}/{file}'
            file_desc: int = os.open(filepath, os.O_RDONLY)
            blocks: int = 0
            while True:
                data: bytes = os.read(file_desc, blocksize)
                if not data:
                    break

                tree.append_entry(data)
                blocks += 1

            os.close(file_desc)
            _LOGGER.debug(
                f'Added file {file} with {blocks} blocks to merkle tree'
            )

        return tree

    def find(self, data: bytes) -> Node | KeyError:
        '''
        Find the data node in the merkle tree for the data.

        :param data: the data that included previously in the Merkle tree
        :raises: TypeError, KeyError
        '''

        if not isinstance(data, bytes):
            raise TypeError('data must be of type bytes')

        hasher: MerkleHasher = MerkleHasher('sha256')
        digest: bytes = hasher.hash_buff(data)

        for node in self.leaves:
            if node.digest == digest:
                return node

        raise KeyError(f'No node found for data with digest {digest.hex()}')
