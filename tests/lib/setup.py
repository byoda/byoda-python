'''
Helper functions to set up tests

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import shutil

from byoda import config

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.servers.pod_server import PodServer

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType
from byoda.datatypes import CloudType

from byoda.storage.filestorage import FileStorage

from byoda.storage.pubsub import PubSubNng

from podserver.util import get_environment_vars

from tests.lib.util import get_test_uuid


async def setup_network(test_dir: str) -> dict[str, str]:
    # Deletes files from tmp directory. Possible race condition
    # with other process so we do it right at the start
    PubSubNng.cleanup()

    config.debug = True

    if test_dir:
        try:
            shutil.rmtree(test_dir)
        except FileNotFoundError:
            pass

        os.makedirs(test_dir)
    else:
        test_dir = '/tmp'

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

    server: PodServer = PodServer(
        cloud_type=CloudType.LOCAL,
        bootstrapping=bool(network_data.get('bootstrap'))
    )
    config.server = server

    await config.server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType(network_data['cloud']),
        bucket_prefix=network_data['bucket_prefix'],
        root_dir=network_data['root_dir']
    )

    network = Network(network_data, network_data)
    await network.load_network_secrets()

    config.test_case = True

    server.network = network
    server.paths = network.paths

    config.server.paths = network.paths

    return network_data


async def setup_account(network_data: dict[str, str]) -> Account:
    server = config.server
    local_storage: FileStorage = server.local_storage

    account = Account(network_data['account_id'], server.network)
    await account.paths.create_account_directory()

    server.account = account

    account.password = network_data.get('account_secret')

    await account.create_account_secret()

    # Save the cert file and unecrypted private key to local storage
    await account.tls_secret.save(
        account.private_key_password, overwrite=True,
        storage_driver=local_storage
    )
    account.tls_secret.save_tmp_private_key()
    await account.create_data_secret()
    account.data_secret.create_shared_key()
    await account.register()

    await server.get_registered_services()

    await config.server.set_data_store(
        DataStoreType.SQLITE, account.data_secret
    )

    services = list(server.network.service_summaries.values())
    service = [
        service
        for service in services
        if service['name'] == 'addressbook'
    ][0]

    global ADDRESSBOOK_SERVICE_ID
    ADDRESSBOOK_SERVICE_ID = service['service_id']
    global ADDRESSBOOK_VERSION
    ADDRESSBOOK_VERSION = service['version']

    member_id = get_test_uuid()
    await account.join(
        ADDRESSBOOK_SERVICE_ID, ADDRESSBOOK_VERSION, local_storage,
        member_id=member_id, local_service_contract='addressbook.json'
    )

    return account
