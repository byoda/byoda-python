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

from passlib.context import CryptContext

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.servers.pod_server import PodServer

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.datastore.cache_store import CacheStoreType

from byoda.datatypes import CloudType

from byoda.storage.filestorage import FileStorage

from byoda.storage.pubsub_nng import PubSubNng

from podserver.util import get_environment_vars

from byoda import config

from tests.lib.util import get_test_uuid
from tests.lib.defines import MODTEST_FQDN
from tests.lib.defines import MODTEST_APP_ID
from tests.lib.defines import CDN_APP_ID
from tests.lib.defines import CDN_ORIGIN_SITE_ID

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import ADDRESSBOOK_VERSION


def mock_environment_vars(test_dir: str) -> None:
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
    os.environ['MODERATION_FQDN'] = MODTEST_FQDN
    os.environ['MODERATION_APP_ID'] = str(MODTEST_APP_ID)
    os.environ['CDN_APP_ID'] = str(CDN_APP_ID)
    os.environ['CDN_ORIGIN_SITE_ID'] = CDN_ORIGIN_SITE_ID


async def setup_network(delete_tmp_dir: bool = True) -> dict[str, str]:
    '''
    Sets up the network for test clients
    '''

    config.debug = True

    data: dict[str, str] = get_environment_vars()

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

    config.server.paths = network.paths

    config.trace_server = os.environ.get(
        'TRACE_SERVER', config.trace_server
    )

    return data


async def setup_account(data: dict[str, str], test_dir: str = None,
                        local_service_contract: str = 'addressbook.json',
                        clean_pubsub: bool = True,
                        service_id: int = ADDRESSBOOK_SERVICE_ID,
                        version: int = ADDRESSBOOK_VERSION
                        ) -> Account:
    # Deletes files from tmp directory. Possible race condition
    # with other process so we do it right at the start
    if clean_pubsub:
        PubSubNng.cleanup()

    if test_dir and local_service_contract:
        dest: str = f'{test_dir}/{local_service_contract}'
        dest_dir: str = os.path.dirname(dest)
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copyfile(local_service_contract, dest)

    server: PodServer = config.server
    local_storage: FileStorage = server.local_storage

    account = Account(data['account_id'], server.network)
    await account.paths.create_account_directory()

    server.account = account

    password_hash_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    account.password = password_hash_context.hash(data['account_secret'])

    await account.create_account_secret()
    if not account.tls_secret.cert:
        await account.tls_secret.load(password=data['private_key_password'])
    else:
        # Save the cert file and unecrypted private key to local storage
        await account.tls_secret.save(
            account.private_key_password, overwrite=True,
            storage_driver=local_storage
        )
    account.tls_secret.save_tmp_private_key()

    if not account.data_secret:
        await account.create_data_secret()
    elif (not account.data_secret.cert
            and not await account.data_secret.cert_file_exists()):
        await account.create_data_secret()
    else:
        await account.data_secret.load(
            with_private_key=True, password=data['private_key_password']
        )
    account.data_secret.create_shared_key()
    await account.register()

    await server.get_registered_services()

    await server.set_data_store(
        DataStoreType.SQLITE, account.data_secret
    )

    await server.set_cache_store(CacheStoreType.SQLITE)

    services = list(server.network.service_summaries.values())
    service: list[dict[str, any]] = [
        service
        for service in services
        if service['name'] == 'addressbook'
    ][0]

    global ADDRESSBOOK_SERVICE_ID
    ADDRESSBOOK_SERVICE_ID = service['service_id']
    global ADDRESSBOOK_VERSION
    ADDRESSBOOK_VERSION = service['version']

    member_id: UUID = get_test_uuid()
    await account.join(
        service_id, version, local_storage,
        member_id=member_id, local_service_contract=local_service_contract
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
