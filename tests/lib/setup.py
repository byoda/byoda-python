'''
Helper functions to set up tests

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import os
import shutil
from uuid import uuid4, UUID
from typing import Dict

from byoda import config

from byoda.datamodel.network import Network

from byoda.servers.pod_server import PodServer

from byoda.datastore.document_store import DocumentStoreType
from byoda.datatypes import CloudType

from podserver.util import get_environment_vars


def get_test_uuid() -> UUID:
    id = str(uuid4())
    id = 'aaaaaaaa' + id[8:]
    id = UUID(id)
    return id


async def setup_network(test_dir: str) -> Dict:
    config.debug = True
    try:
        shutil.rmtree(test_dir)
    except FileNotFoundError:
        pass

    os.makedirs(test_dir)
    shutil.copy('tests/collateral/addressbook.json', test_dir)

    os.environ['ROOT_DIR'] = test_dir
    os.environ['BUCKET_PREFIX'] = 'byoda'
    os.environ['CLOUD'] = 'LOCAL'
    os.environ['NETWORK'] = 'byoda.net'
    os.environ['ACCOUNT_ID'] = str(get_test_uuid())
    os.environ['ACCOUNT_SECRET'] = 'test'
    os.environ['LOGLEVEL'] = 'DEBUG'
    os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
    os.environ['BOOTSTRAP'] = 'BOOTSTRAP'

    network_data = get_environment_vars()

    network = Network(network_data, network_data)
    await network.load_network_secrets()

    config.test_case = True

    config.server = PodServer(network)
    config.server.network = network

    await config.server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType(network_data['cloud']),
        bucket_prefix=network_data['bucket_prefix'],
        root_dir=network_data['root_dir']
    )

    config.server.paths = network.paths

    return network_data
