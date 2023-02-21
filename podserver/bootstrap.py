#!/usr/bin/env python3

'''
Gets everything in place for the podserver and podworker to run. We run the
steps here to avoid race conditions in the multiple parallel processes that
are started to run the podserver.

Suported environment variables:
CLOUD: 'AWS', 'AZURE', 'GCP', 'LOCAL'
BUCKET_PREFIX
NETWORK
ACCOUNT_ID
ACCOUNT_SECRET
PRIVATE_KEY_SECRET: secret to protect the private key
LOGLEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL
ROOT_DIR: where files need to be cached (if object storage is used) or stored

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import sys
import asyncio

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account

from byoda.datatypes import CloudType
from byoda.datatypes import IdType
from byoda.datatypes import StorageType

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType

from byoda.servers.pod_server import PodServer

from byoda.util.nginxconfig import NginxConfig, NGINX_SITE_CONFIG_DIR

from byoda.util.logger import Logger

from byoda import config


from podserver.util import get_environment_vars

_LOGGER = None

LOGFILE = '/var/www/wwwroot/logs/bootstrap.log'


async def main(argv):
    # Remaining environment variables used:
    data = get_environment_vars()

    global _LOGGER
    _LOGGER = Logger.getLogger(
        argv[0], json_out=False, debug=data.get('DEBUG', False),
        loglevel=data.get('loglevel', 'INFO'), logfile=LOGFILE
    )
    _LOGGER.debug(
        f'Starting podworker {data["bootstrap"]}: '
        f'daemonize: {data["daemonize"]}'
    )

    try:
        config.server = PodServer(cloud_type=CloudType(data['cloud']))
        server = config.server

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE,
            server.cloud,
            bucket_prefix=data['bucket_prefix'],
            root_dir=data['root_dir']
        )
        network = Network(data, data)
        await network.load_network_secrets()

        try:
            await network.root_ca.save(
                storage_driver=server.local_storage
            )
        except PermissionError:
            # We get permission error if the file already exists
            pass

        server.network = network
        server.paths = network.paths

        await server.set_data_store(DataStoreType.SQLITE)

        account = Account(data['account_id'], network)
        await account.paths.create_account_directory()

        account.password = data.get('account_secret')

        if data.get('bootstrap'):
            _LOGGER.info('Running bootstrap tasks')
            await run_bootstrap_tasks(account)
        else:
            await account.tls_secret.load(
                password=account.private_key_password
            )
            await account.data_secret.load(
                password=account.private_key_password
            )

        try:
            # Unencrypted private key is needed for nginx and aiohttp
            await account.tls_secret.save(
                password=data['private_key_password'], overwrite=True,
                storage_driver=server.local_storage
            )
        except PermissionError:
            _LOGGER.debug('Account cert/key already exists on local storage')
            account.tls_secret.save_tmp_private_key()

        server.account = account

        await account.register()

        # Save local copies for nginx and aiohttp to use
        account.tls_secret.save_tmp_private_key()

        nginx_config = NginxConfig(
            directory=NGINX_SITE_CONFIG_DIR,
            filename='virtualserver.conf',
            identifier=data['account_id'],
            subdomain=IdType.ACCOUNT.value,
            cert_filepath=(
                server.local_storage.local_path + '/' +
                account.tls_secret.cert_file
            ),
            key_filepath=account.tls_secret.unencrypted_private_key_file,
            alias=network.paths.account,
            network=network.name,
            public_cloud_endpoint=network.paths.storage_driver.get_url(
                storage_type=StorageType.PUBLIC
            ),
            private_cloud_endpoint=network.paths.storage_driver.get_url(
                storage_type=StorageType.PRIVATE
            ),
            port=PodServer.HTTP_PORT,
            root_dir=server.network.paths.root_directory,
            custom_domain=server.custom_domain,
            shared_webserver=server.shared_webserver
        )

        nginx_config.create(htaccess_password=account.password)
        nginx_config.reload()

        await account.load_memberships()

        for member in account.memberships.values():
            await member.update_registration()
            await member.create_nginx_config()

    except Exception:
        _LOGGER.exception('Exception during startup')
        raise


async def run_bootstrap_tasks(account: Account):
    '''
    When we are bootstrapping, we create any data that is missing from
    the data store.
    '''

    account_id = account.account_id

    _LOGGER.debug('Starting bootstrap tasks')
    try:
        await account.tls_secret.load(
            password=account.private_key_password
        )
        common_name = account.tls_secret.common_name
        if not common_name.startswith(str(account.account_id)):
            error_msg = (
                f'Common name of existing account secret {common_name} '
                f'does not match ACCOUNT_ID environment variable {account_id}'
            )
            _LOGGER.exception(error_msg)
            raise ValueError(error_msg)
        _LOGGER.debug('Read account TLS secret')
    except FileNotFoundError:
        try:
            await account.create_account_secret()
            _LOGGER.info('Created account secret during bootstrap')
        except Exception:
            _LOGGER.exception('Exception during startup')
            raise
    except Exception:
        _LOGGER.exception('Exception during startup')
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

    _LOGGER.info('Podworker completed bootstrap')


if __name__ == '__main__':
    asyncio.run(main(sys.argv))
