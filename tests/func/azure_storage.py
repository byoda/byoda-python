#!/usr/bin/env python3

'''
Test the Azure Storage code

As these test cases are directly run against the web APIs, they mock
the headers that would normally be set by the reverse proxy

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license
'''

import requests

from byoda.storage import FileStorage
from byoda.datatypes import StorageType, CloudType

azure = FileStorage.get_storage(
    CloudType.AZURE, 'byoda', root_dir='/tmp/byoda-azurestorage'
)

azure.copy(
    '/etc/profile', 'test/profile', storage_type=StorageType.PRIVATE
)

data = azure.read('test/profile')

write_filepath = 'test/subdir/profile-write'
azure.write(write_filepath, data)
azure.write('test/anothersubdir/profile-write', data)

exists = azure.exists(write_filepath)
print('Exists:', exists)

subdirs = azure.get_folders('test/')
print('Subdirs #:', len(subdirs))

subdirs = azure.get_folders('test/', prefix='sub')
print('Subdirs with prefix "sub" #:', len(subdirs))

url = azure.get_url() + 'test/profile'
response = requests.get(url)
print('HTTP status code', response.status_code)
