#!/usr/bin/env python3

'''
Gets everything in place for the podserver and pod_worker to run. We run the
steps here to avoid race conditions in the multiple parallel processes that
are started to run the podserver.

Bootstrap use cases are based on
- Whether an account already exists
- Whether the BOOTSTRAP environment variable is set
- Whether the Account DB is available (locally or from the cloud)
- Whether the Account DB can be downloaded from object storage

Suported environment variables:
CLOUD: 'AWS', 'AZURE', 'GCP', 'LOCAL'
PUBLIC_BUCKET (*)
RESTRICTED_BUCKET (*)
PUBLIC_BUCKET (*)
NETWORK
ACCOUNT_ID
ACCOUNT_USERNAME
ACCOUNT_SECRET
PRIVATE_KEY_SECRET: secret to protect the private key
LOGLEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL
ROOT_DIR: where files need to be cached (if object storage is used) or stored
CDN_APP_ID: the UUID of the CDN app
CDN_ORIGIN_SITE_ID: the two- or three letter site_id for the CDN origin site

(*) Because Azure Storage Accounts work different than AWS/GCP S3 buckets, for
Azure we use a single storage account with three containers instead of 3
buckets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os
import sys
import logging
import asyncio

from uuid import UUID

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.datatypes import CloudType
from byoda.datatypes import IdType
from byoda.datatypes import StorageType

from byoda.datastore.data_store import DataStoreType
from byoda.datastore.cache_store import CacheStoreType

from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.pod_server import PodServer

from byoda.util.angieconfig import AngieConfig, ANGIE_SITE_CONFIG_DIR

from byoda.util.logger import Logger

from byoda import config


from podserver.util import get_environment_vars

_LOGGER: Logger | None = None

LOGFILE: str = os.environ.get('LOGDIR', '/var/log/byoda') + '/bootstrap.log'


async def main(argv) -> None:
    # Remaining environment variables used:
    data: dict[str, str | int | bool] = get_environment_vars()

    debug: bool = data.get('debug', False)
    if debug and str(debug).lower() in ('true', 'debug', '1'):
        config.info = True
        # Make our files readable by everyone, so we can
        # use tools like call_data_api.py to debug the server
        os.umask(0o0000)
    else:
        os.umask(0o0022)

    log_file = data.get('logdir', '/var/log/byoda') + '/bootstrap.log'
    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], json_out=True, debug=config.debug,
        loglevel=data.get('worker_loglevel', 'WARNING'),
        logfile=log_file
    )
    _LOGGER.info(
        f'Starting bootstrap with variable bootstrap={data["bootstrap"]} '
        f'and debug: {config.debug}'
    )

    try:
        server: PodServer = PodServer(
            cloud_type=CloudType(data['cloud']),
            bootstrapping=bool(data.get('bootstrap')),
            db_connection_string=data.get('db_connection')
        )
        config.server = server

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            server.cloud,
            private_bucket=data['private_bucket'],
            restricted_bucket=data['restricted_bucket'],
            public_bucket=data['public_bucket'],
            root_dir=data['root_dir']
        )

        _LOGGER.debug('Setting up the network')
        network: Network = Network(data, data)
        await network.load_network_secrets()

        try:
            await network.root_ca.save(
                storage_driver=server.local_storage
            )
        except PermissionError:
            # We get permission error if the file already exists
            pass

        _LOGGER.debug('Setting up the network')
        server.network = network
        server.paths = network.paths

        _LOGGER.debug('Setting up the account')
        account: Account = Account(data['account_id'], network)
        server.account = account

        await account.paths.create_account_directory()

        account.password = data.get('account_secret')

        if data.get('bootstrap'):
            await run_bootstrap_tasks(account)
            # Saving account TLS certchain private key to local files
            # so that Apiclient can use it to register the account
            await account.tls_secret.save(
                account.private_key_password, overwrite=True,
                storage_driver=server.local_storage
            )
            account.tls_secret.save_tmp_private_key()
            await account.data_secret.save(
                account.private_key_password, overwrite=True,
                storage_driver=server.local_storage
            )
            await account.register()
        else:
            await server.load_secrets()
            # Saving account TLS certchain private key to local files
            # so that Apiclient can use it to register the account
            await account.tls_secret.save(
                account.private_key_password, overwrite=True,
                storage_driver=server.local_storage
            )
            account.tls_secret.save_tmp_private_key()
            await account.update_registration()
            await account.load_protected_shared_key()

        await server.set_data_store(
            DataStoreType.POSTGRES, account.data_secret
        )
        await server.set_cache_store(CacheStoreType.POSTGRES)

        # Remaining environment variables used:
        server.custom_domain = data['custom_domain']
        server.shared_webserver = data['shared_webserver']

        angie_config = AngieConfig(
            directory=ANGIE_SITE_CONFIG_DIR,
            filename='virtualserver.conf',
            identifier=data['account_id'],
            subdomain=IdType.ACCOUNT.value,
            cert_filepath=(
                server.local_storage.local_path + '/' +
                account.tls_secret.cert_file
            ),
            key_filepath=account.tls_secret.get_tmp_private_key_filepath(),
            alias=network.paths.account,
            network=network.name,
            public_cloud_endpoint=network.paths.storage_driver.get_url(
                storage_type=StorageType.PUBLIC
            ),
            restricted_cloud_endpoint=network.paths.storage_driver.get_url(
                storage_type=StorageType.RESTRICTED
            ),
            private_cloud_endpoint=network.paths.storage_driver.get_url(
                storage_type=StorageType.PRIVATE
            ),
            cloud=server.cloud.value,
            port=PodServer.HTTP_PORT,
            root_dir=server.network.paths.root_directory,
            custom_domain=server.custom_domain,
            shared_webserver=server.shared_webserver,
            public_bucket=network.paths.storage_driver.get_bucket(
                StorageType.PUBLIC
            ),
            restricted_bucket=network.paths.storage_driver.get_bucket(
                StorageType.RESTRICTED
            ),
            private_bucket=network.paths.storage_driver.get_bucket(
                StorageType.PRIVATE
            ),
        )

        angie_config.create()

        await account.load_memberships()

        await server.bootstrap_join_services(data['join_service_ids'])

        await account.load_memberships()

        for member in account.memberships.values():
            member.tls_secret.save_tmp_private_key()
            await member.tls_secret.save(
                member.private_key_password, overwrite=True,
                storage_driver=server.local_storage
            )
            await member.update_registration()
            await member.create_angie_config()

    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

    logging.shutdown()


async def run_bootstrap_tasks(account: Account) -> None:
    '''
    When we are bootstrapping, we create any data that is missing from
    the data store.
    '''

    account_id: UUID = account.account_id

    _LOGGER.debug('Starting bootstrap tasks')
    try:
        await account.tls_secret.load(
            password=account.private_key_password
        )
        common_name: str = account.tls_secret.common_name
        if not common_name.startswith(str(account.account_id)):
            error_msg: str = (
                f'Common name of existing account secret {common_name} '
                f'does not match ACCOUNT_ID environment variable {account_id}'
            )
            _LOGGER.exception(error_msg)
            raise ValueError(error_msg)
        _LOGGER.debug('Read existing account TLS secret')
    except FileNotFoundError:
        try:
            await account.create_account_secret()
            _LOGGER.info('Created new account secret during bootstrap')
        except Exception as exc:
            _LOGGER.exception(f'Exception during startup: {exc}')
            raise
    except Exception as exc:
        _LOGGER.exception(f'Exception during startup: {exc}')
        raise

    try:
        await account.data_secret.load(
            password=account.private_key_password
        )
        _LOGGER.debug('Read account data secret')
    except FileNotFoundError:
        try:
            await account.create_data_secret()
            _LOGGER.info('Created account data secret during bootstrap')
        except Exception:
            raise
    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

    _LOGGER.info('Bootstrap completed successfully')

    try:
        await account.load_protected_shared_key()
        _LOGGER.debug('Read account shared secret')
    except FileNotFoundError:
        try:
            account.data_secret.create_shared_key()
            _LOGGER.info('Created account shared secret during bootstrap')
            await account.save_protected_shared_key()
            _LOGGER.info('Saved account shared secret during bootstrap')
        except Exception:
            raise
    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

if __name__ == '__main__':
    asyncio.run(main(sys.argv))
