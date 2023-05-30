'''
Helper functions to set up tests

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import shutil

from uuid import UUID

import orjson

from byoda import config

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.servers.pod_server import PodServer

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType
from byoda.datatypes import CloudType

from byoda.storage.filestorage import FileStorage

from byoda.storage.pubsub_nng import PubSubNng

from podserver.util import get_environment_vars

from tests.lib.util import get_test_uuid


def mock_environment_vars(test_dir: str):
    '''
    Sets environment variables needed by setup_network() and setup_account
    '''

    os.environ['ROOT_DIR'] = test_dir
    os.environ['PRIVATE_BUCKET'] = 'byoda'
    os.environ['RESTRICTED_BUCKET'] = 'byoda'
    os.environ['PUBLIC_BUCKET'] = 'byoda'
    os.environ['CLOUD'] = 'LOCAL'
    os.environ['NETWORK'] = 'byoda.net'
    os.environ['ACCOUNT_ID'] = str(get_test_uuid())
    os.environ['ACCOUNT_SECRET'] = 'test'
    os.environ['LOGLEVEL'] = 'DEBUG'
    os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
    os.environ['BOOTSTRAP'] = 'BOOTSTRAP'


async def setup_network(delete_tmp_dir: bool = True) -> dict[str, str]:
    '''
    Sets up the network for test clients
    '''

    config.debug = True

    data = get_environment_vars()

    if delete_tmp_dir:
        try:
            shutil.rmtree(data['root_dir'])
        except FileNotFoundError:
            pass

    os.makedirs(data['root_dir'], exist_ok=True)

    shutil.copy('tests/collateral/addressbook.json', data['root_dir'])

    server: PodServer = PodServer(
        cloud_type=CloudType.LOCAL,
        bootstrapping=bool(data.get('bootstrap'))
    )
    config.server = server

    await server.set_document_store(
        DocumentStoreType.OBJECT_STORE, server.cloud,
        private_bucket=data['private_bucket'],
        restricted_bucket=data['restricted_bucket'],
        public_bucket=data['public_bucket'],
        root_dir=data['root_dir']
    )

    network = Network(data, data)
    await network.load_network_secrets()

    config.test_case = True

    server.network = network
    server.paths = network.paths

    config.server.paths = network.paths

    return data


async def setup_account(data: dict[str, str]) -> Account:
    # Deletes files from tmp directory. Possible race condition
    # with other process so we do it right at the start
    PubSubNng.cleanup()

    server = config.server
    local_storage: FileStorage = server.local_storage

    account = Account(data['account_id'], server.network)
    await account.paths.create_account_directory()

    server.account: Account = account

    account.password: str = data.get('account_secret')

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
        if service['name'] == 'byoda-tube'
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


def get_account_id(data: dict[str, str]) -> str:
    '''
    Gets the account ID used by the test POD server

    :param data: The dict as returned by podserver.util.get_environment_vars
    :returns: the account ID
    '''

    with open(f'{data["root_dir"]}/account_id', 'rb') as file_desc:
        account_id = orjson.loads(file_desc.read())

    return account_id


def write_account_id(data: dict[str, str]):
    '''
    Writes the account ID to a local file so that test clients
    can use the same account ID as the test podserver
    '''

    with open(f'{data["root_dir"]}/account_id', 'wb') as file_desc:
        file_desc.write(orjson.dumps(data['account_id']))
