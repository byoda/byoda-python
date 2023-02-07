'''
Various utility classes, variables and functions

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from byoda.datamodel.member import Member

from byoda.storage import FileStorage

from byoda.servers.pod_server import PodServer

from byoda.datastore.document_store import DocumentStore
from byoda.datastore.data_store import DataStore

from byoda.util.paths import Paths


async def sync_datastore_from_cloud(server: PodServer):
    '''
    Download database files for the account and its memberships from the cloud
    '''

    doc_store: DocumentStore = server.document_store
    data_store: DataStore = server.data_store

    paths: Paths = server.paths

    cloud_file_store: FileStorage = doc_store.backend

    if not os.path.exists(data_store.backend.account_db_file):
        cloud_filepath = (
            paths.get(Paths.ACCOUNT_DATA_DIR) + '/' +
            os.path.basename(data_store.account_db_file)
        )
        if await cloud_file_store.exists(cloud_filepath):
            data = cloud_file_store.read(cloud_filepath)
            with open(data_store.account_db_file, 'wb') as file_desc:
                file_desc.write(data)

    memberships: dict[str, Member] = data_store.get_memberships()
