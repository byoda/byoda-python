#!/usr/bin/env python3

'''
Test the Azure Storage code

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license
'''

from byoda.storage import FileStorage
from byoda.datatypes import StorageType, CloudType

azure = FileStorage.get_storage(
    CloudType.AZURE, 'byoda', root_dir='/tmp/byoda-azurestorage'
)

azure.copy(
    '/etc/profile', 'test/profile', storage_type=StorageType.PRIVATE
)
