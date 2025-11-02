'''
Helper functions to set up tests

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license
'''

import os
import shutil

from uuid import UUID
from passlib.context import CryptContext

import orjson

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.servers.pod_server import PodServer

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.datastore.cache_store import CacheStoreType

from byoda.datatypes import CloudType

from byoda.storage.filestorage import FileStorage
from byoda.storage.postgres import PostgresStorage
from byoda.storage.pubsub_nng import PubSubNng

from podserver.util import get_environment_vars

from byoda import config

from tests.lib.util import get_test_uuid
from tests.lib.defines import MODTEST_FQDN
from tests.lib.defines import MODTEST_APP_ID
from tests.lib.defines import CDN_APP_ID
from tests.lib.defines import CDN_FQDN
from tests.lib.defines import CDN_ORIGIN_SITE_ID

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import ADDRESSBOOK_VERSION

PASSWORD: str = 'byoda-secret-password'


def mock_environment_vars(test_dir: str, hash_password: bool = True) -> None:
    '''
    Sets environment variables needed by setup_network() and setup_account.
    It sets the hashed value for the ACCOUNT_SECRET if hash_password is True

    :param test_dir:
    :param hash_password: should the environment variable with the account
    password have a hashed password? True is you are running a standalone
    test, False in the test client if the client is calling a separate server
    process
    '''

    os.environ['ROOT_DIR'] = test_dir
    os.environ['PRIVATE_BUCKET'] = 'byoda'
    os.environ['RESTRICTED_BUCKET'] = 'byoda'
    os.environ['PUBLIC_BUCKET'] = 'byoda'
    os.environ['CLOUD'] = 'LOCAL'
    os.environ['NETWORK'] = 'byoda.net'
    os.environ['ACCOUNT_ID'] = str(get_test_uuid())

    os.environ['ACCOUNT_SECRET'] = PASSWORD
    if hash_password:
        password_hash_context = CryptContext(
            schemes=["argon2"], deprecated="auto"
        )
        os.environ['ACCOUNT_SECRET'] = password_hash_context.hash(
            PASSWORD.encode('utf-8')
        )

    os.environ['LOGLEVEL'] = 'DEBUG'
    os.environ['PRIVATE_KEY_SECRET'] = 'byoda'
    os.environ['BOOTSTRAP'] = 'BOOTSTRAP'
    os.environ['MODERATION_FQDN'] = MODTEST_FQDN
    os.environ['MODERATION_APP_ID'] = str(MODTEST_APP_ID)
    os.environ['CDN_APP_ID'] = str(CDN_APP_ID)
    os.environ['CDN_FQDN'] = CDN_FQDN
    os.environ['CDN_ORIGIN_SITE_ID'] = CDN_ORIGIN_SITE_ID

    with open('tests/collateral/local/test_postgres_db') as file_desc:
        os.environ['DB_CONNECTION'] = file_desc.read().strip()


async def setup_network(delete_tmp_dir: bool = True) -> dict[str, str]:
    '''
    Sets up the network for test clients
    '''

    config.debug = True
    config.test_case = True

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
        bootstrapping=bool(data.get('bootstrap')),
        db_connection_string=data.get('db_connection')
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
    os.makedirs(f'{data["root_dir"]}/network-byoda.net', exist_ok=True)
    ca_file: str = 'network-byoda.net-root-ca-cert.pem'
    shutil.copyfile(
        f'tests/collateral/{ca_file}',
        f'{data['root_dir']}/network-byoda.net/{ca_file}'
    )
    await network.load_network_secrets()

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
                        version: int = ADDRESSBOOK_VERSION,
                        member_id: UUID | None = None,
                        store_type: DataStoreType = DataStoreType.POSTGRES
                        ) -> Account:
    # Deletes files from tmp directory. Possible race condition
    # with other process so we do it right at the start
    if clean_pubsub:
        PubSubNng.cleanup()

    if test_dir and local_service_contract:
        dest: str = f'{test_dir}/{local_service_contract}'
        dest_dir: str = os.path.dirname(dest)
        os.makedirs(dest_dir, exist_ok=True)
        if service_id == ADDRESSBOOK_SERVICE_ID:
            shutil.copyfile(local_service_contract, dest)

    server: PodServer = config.server
    local_storage: FileStorage = server.local_storage

    if store_type == DataStoreType.POSTGRES:
        PostgresStorage._destroy_database(data['db_connection'])

    account = Account(data['account_id'], server.network)
    await account.paths.create_account_directory()

    server.account = account

    if data['account_secret'].startswith('$2b$'):
        account.password = data['account_secret']
    else:
        password_hash_context = CryptContext(
            schemes=["argon2"], deprecated="auto"
        )
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

    await server.set_data_store(store_type, account.data_secret)

    if store_type != DataStoreType.POSTGRES:
        cache_store_type: CacheStoreType = CacheStoreType.SQLITE
    else:
        cache_store_type: CacheStoreType = CacheStoreType.POSTGRES
    await server.set_cache_store(cache_store_type)

    if not member_id:
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
