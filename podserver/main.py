'''
POD server for Bring Your Own Data and Algorithms

The podserver relies on podserver/bootstrap.py to set up
the account, its secrets, restoring the database files
from the cloud storage, registering the pod and creating
the angie configuration files for the account and for
existing memberships.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import os
import sys

from logging import Logger
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.app import CdnApp

from byoda.datatypes import CloudType

from byoda.datastore.document_store import DocumentStoreType
from byoda.datastore.data_store import DataStoreType
from byoda.datastore.cache_store import CacheStoreType

from byoda.storage.pubsub_nng import PubSubNng

from byoda.servers.pod_server import PodServer

from byoda.util.fastapi import setup_api, update_cors_origins

from podserver.util import get_environment_vars

from byoda import config

from .routers import account as AccountRouter
from .routers import member as MemberRouter
from .routers import authtoken as AuthTokenRouter
from .routers import status as StatusRouter
from .routers import accountdata as AccountDataRouter
from .routers import content_token as ContentTokenRouter

_LOGGER: Logger | None = None

DIR_API_BASE_URL = 'https://dir.{network}/api'


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:

    # HACK: Deletes files from tmp directory. Possible race condition
    # with other process so we do it right at the start
    PubSubNng.cleanup()

    network_data: dict[str, str | int | bool | None] = get_environment_vars()

    server: PodServer = PodServer(
        bootstrapping=bool(network_data.get('bootstrap')),
        db_connection_string=network_data.get('db_connection'),
        http_port=network_data.get('http_port'),
        host_root_dir=network_data.get('host_root_dir'),
    )

    config.server = server

    # Remaining environment variables used:
    server.custom_domain = network_data['custom_domain']
    server.shared_webserver = network_data['shared_webserver']
    server.cdn_fqdn = network_data.get('cdn_fqdn')
    server.cdn_origin_site_id = network_data.get('cdn_origin_site_id')

    debug: bool = network_data.get('debug', False)
    if debug and str(debug).lower() in ('true', 'debug', '1'):
        config.debug = True
        # Make our files readable by everyone, so we can
        # use tools like call_data_api.py to debug the server
        os.umask(0o0000)
    else:
        os.umask(0x0077)

    logfile: str = network_data.get('logdir', '/var/log/byoda') + '/pod.log'
    global _LOGGER
    _LOGGER = ByodaLogger.getLogger(
        sys.argv[0], json_out=True, debug=config.debug,
        loglevel=network_data['loglevel'], logfile=logfile
    )

    _LOGGER.debug(
        f'Setting up logging: debug {config.debug}, '
        f'loglevel {network_data["loglevel"]}, logfile {logfile}'
    )

    config.log_requests = network_data.get('log_requests', True)
    if not config.log_requests:
        _LOGGER.info('Logging of data requests is disabled')

    await server.set_document_store(
        DocumentStoreType.OBJECT_STORE,
        cloud_type=CloudType(network_data['cloud']),
        private_bucket=network_data['private_bucket'],
        restricted_bucket=network_data['restricted_bucket'],
        public_bucket=network_data['public_bucket'],
        root_dir=network_data['root_dir']
    )

    network = Network(network_data, network_data)
    await network.load_network_secrets()

    server.network = network
    server.paths = network.paths

    account = Account(network_data['account_id'], network)
    account.password = network_data.get('account_secret')

    await account.load_secrets()

    server.account = account

    await server.set_data_store(
        DataStoreType.POSTGRES, account.data_secret
    )

    await server.set_cache_store(CacheStoreType.POSTGRES)

    await server.get_registered_services()

    cors_origins: set[str] = set(
        [
            f'https://proxy.{network.name}',
            f'https://{account.tls_secret.common_name}'
        ]
    )

    if server.custom_domain:
        cors_origins.add(f'https://{server.custom_domain}')

    await account.load_memberships()

    auto_joins: list[int] = network_data['join_service_ids']

    for member in account.memberships.values():
        await member.enable_data_apis(
            app, server.data_store, server.cache_store
        )

        await member.tls_secret.save(
            password=member.private_key_password,
            storage_driver=server.local_storage,
            overwrite=True
        )
        await member.data_secret.save(
            password=member.private_key_password,
            storage_driver=server.local_storage,
            overwrite=True
        )

        if (network_data.get('cdn_fqdn')
                and network_data.get('cdn_origin_site_id')):
            cdn_app: CdnApp = CdnApp(
                network_data['cdn_app_id'], member.service,
                network_data.get('cdn_fqdn'),
                network_data.get('cdn_origin_site_id')
            )
            server.apps[cdn_app.app_id] = cdn_app

        # We may have joined services (either the enduser or the bootstrap
        # script with the 'auto-join' environment variable. But account.join()
        # can not persist the membership settings so we do that here. We check
        # here whether those values have been set and, if not, we set them.
        try:
            await member.load_settings()
        except ValueError:
            member.auto_upgrade = member.service.service_id in auto_joins
            await member.data.initialize()

        cors_origins.add(f'https://{member.tls_secret.common_name}')

    _LOGGER.debug(
        f'Tracing to {config.trace_server}'
    )

    _LOGGER.debug('Lifespan startup complete')
    update_cors_origins(cors_origins)

    yield

    _LOGGER.info('Shutting down pod server')


config.trace_server = os.environ.get('TRACE_SERVER', config.trace_server)

app = setup_api(
    'BYODA pod server', 'The pod server for a BYODA network',
    'v0.0.1', [
        AccountRouter, MemberRouter, AuthTokenRouter, StatusRouter,
        AccountDataRouter, ContentTokenRouter
    ],
    lifespan=lifespan, trace_server=config.trace_server,
)

config.app = app
