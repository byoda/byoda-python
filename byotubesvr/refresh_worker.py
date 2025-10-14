#!/usr/bin/python3

'''
Worker that performs queries against registered members of
the service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2024
:license    : GPLv3
'''

import os
import sys

from datetime import UTC
from datetime import datetime

from anyio import run
from anyio import sleep

from prometheus_client import start_http_server
from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema
from byoda.datamodel.config import ServerConfig

from byoda.models.data_api_models import EdgeResponse as Edge

from byoda.storage.filestorage import FileStorage

from byoda.util.paths import Paths

from byoda.servers.service_server import ServiceServer

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from byoda.datacache.asset_cache import AssetCache

# Time out waiting for a member from the list of members to
# get info from the Person table
MAX_WAIT: int = 3 * 60

CACHE_STALE_THRESHOLD: int = 4 * 60 * 60

ASSET_CLASS: str = 'public_assets'

PROMETHEUS_EXPORTER_PORT: int = 5010


async def main() -> None:
    '''
    Takes the oldest asset from the list:all_assets list and refresh it
    if it is about to expire.
    - If the asset is not about to expire, it puts the oldest asset back
    - If it is stale and gets refreshed, it pushes the asset back as
    newest asset
    - If it is stale and fails to get refreshed then the item does not
    get back in the list of all_assets

    :param time_available: the time we have to refresh assets before returning
    :param tls_secret: the secret to use to refresh the asset against the pod
    '''

    service: Service
    server: ServiceServer

    service, server = await setup_server()
    asset_cache: AssetCache = server.asset_cache

    log_data: dict[str, any] = {
        'service_id': service.service_id,
    }
    _LOGGER.debug('Starting service refresh worker', extra=log_data)

    metrics: dict[str, Counter | Gauge] = config.metrics

    wait_time: float = 0.0
    while True:
        log_data['wait_time'] = wait_time
        if wait_time:
            _LOGGER.debug('Sleeping', extra=log_data)
            await sleep(wait_time)

        edge: Edge | None = None
        try:
            metrics['svc_refresh_getting_oldest_asset'].inc()
            cursor: str
            expires_at: float | int
            cursor, expires_at = await asset_cache.get_oldest_expired_item(
                stale_window=CACHE_STALE_THRESHOLD
            )
            if not cursor:
                _LOGGER.debug(
                    'No stale or expired assets to refresh', extra=log_data
                )
                metrics['svc_refresh_no_expired_assets_available'].inc()
                wait_time = min(wait_time * 2, MAX_WAIT)
                wait_time = max(wait_time, 1)
                continue
            log_data['cursor'] = cursor
            log_data['expires_at'] = expires_at
            edge = await asset_cache.get_asset_by_key(cursor)
        except FileNotFoundError:
            _LOGGER.debug(
                'Expired or stale asset not found', extra=log_data
            )
            metrics['svc_refresh_assets_not_found'].inc()
            wait_time = min(wait_time * 2, MAX_WAIT)
            wait_time = max(wait_time, 1)
            continue
        except Exception as exc:
            _LOGGER.debug(
                'Failed to get oldest asset from the all_assets list',
                extra=log_data | {'exception': exc}
            )
            metrics['svc_refresh_getting_oldest_asset_failures'].inc()
            # Double wait time to at least 1 but do not exceed MAX_WAIT
            wait_time = min(wait_time * 2, MAX_WAIT)
            wait_time = max(wait_time, 1)
            continue

        log_data['asset_id'] = edge.node.asset_id
        log_data['origin'] = edge.origin
        wait_time = expires_at - datetime.now(tz=UTC).timestamp()

        metrics['svc_refresh_assets_oldest_asset_expires_in'].set(wait_time)

        try:
            _LOGGER.debug('We need to refresh asset', extra=log_data)
            metrics['svc_refresh_assets_needing'].inc()
            await asset_cache.refresh_asset(
                edge, ASSET_CLASS, service.tls_secret
            )
            metrics['svc_refresh_assets_runs'].inc()
            if not await asset_cache.add_newest_asset(edge):
                _LOGGER.debug('Failed to store asset in cache', extra=log_data)
                metrics['svc_refresh_assets_failures'].labels(
                    member_id=edge.origin
                ).inc()
        except Exception as exc:
            # Currently, we do not put the asset back in the list
            # if the refresh fails. TODO: have 'retry' lists
            # to process failed refreshes
            _LOGGER.debug(
                'Failed to refresh asset', extra=log_data | {'exception': exc}
            )
            metrics['svc_refresh_assets_failures'].labels(
                member_id=edge.origin
            ).inc()


async def setup_server() -> tuple[Service, ServiceServer]:
    server_config = ServerConfig('svcserver', is_worker=True)
    # HACK: hardcoded location of logfile
    server_config.logfile = '/var/log/byoda/worker-16384-refresh-assets.log'
    verbose: bool = \
        not server_config.debug and server_config.loglevel == 'INFO'

    global _LOGGER
    _LOGGER = ByodaLogger.getLogger(
        sys.argv[0], json_out=True,
        debug=server_config.debug, verbose=verbose,
        logfile=server_config.logfile, loglevel=server_config.loglevel
    )

    if server_config.debug:
        global MAX_WAIT
        MAX_WAIT = 300

    network = Network(
        server_config.server_config, server_config.app_config
    )
    network.paths = Paths(
        network=network.name,
        root_directory=server_config.server_config['root_dir']
    )
    server: ServiceServer = await ServiceServer.setup(network, server_config)
    config.server = server

    listen_port: int = os.environ.get(
        'WORKER_METRICS_PORT', PROMETHEUS_EXPORTER_PORT
    )
    setup_exporter_metrics()
    start_http_server(listen_port)

    _LOGGER.debug(
        'Setup refresh worker completed, now loading network secrets'
    )

    storage = FileStorage(server_config.server_config['root_dir'])
    await server.load_network_secrets(storage_driver=storage)

    _LOGGER.debug('Now loading service secrets')
    await server.load_secrets(
        password=server_config.server_config['private_key_password']
    )

    service: Service = server.service

    if not await service.paths.service_file_exists(service.service_id):
        await service.download_schema(save=True)

    await server.load_schema(verify_contract_signatures=False)
    schema: Schema = service.schema
    schema.get_data_classes(with_pubsub=False)
    schema.generate_data_models('svcserver/codegen', datamodels_only=True)

    await server.setup_asset_cache(
        server_config.server_config['asset_cache'],
        server_config.server_config['asset_cache_readwrite']
    )

    return service, server


def setup_exporter_metrics() -> None:
    config.metrics = {
        'svc_refresh_getting_oldest_asset': Counter(
            'svc_refresh_getting_oldest_asset',
            'Getting the oldest asset from the all_assets list'
        ),
        'svc_refresh_getting_oldest_asset_failures': Counter(
            'svc_refresh_getting_oldest_asset_failures',
            'Getting the oldest asset from the all_assets list failed'
        ),
        'svc_refresh_no_expired_assets_available': Counter(
            'svc_refresh_no_expired_assets_available',
            'number of times no assets had expired'
        ),
        'svc_refresh_no_assets_available_at_all': Counter(
            'svc_refresh_no_assets_available_at_all',
            'number of times we did not have to run the refresh any assets'
        ),
        'svc_refresh_assets_runs': Counter(
            'svc_refresh_assets_runs',
            'number of times the refresh asset procedure has run'
        ),
        'svc_refresh_assets_needing': Counter(
            'svc_refresh_assets_needing',
            'Number of assets needing refresh'
        ),
        'svc_refresh_assets_oldest_asset_expires_in': Gauge(
            'svc_refresh_assets_oldest_asset_expires_in',
            'Seconds until the oldest asset expires'
        ),
        'svc_refresh_assets_failures': Counter(
            'svc_refresh_assets_failures',
            'Number of times we failed to refresh an asset',
            ['member_id']
        ),
        'svc_refresh_assets_not_found': Counter(
            'svc_refresh_assets_not_found',
            'Number of times an asset was not in the cache'
        )
    }


if __name__ == '__main__':
    run(main)
