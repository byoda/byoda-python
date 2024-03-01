#!/usr/bin/python3

'''
Worker that performs queries against registered members of
the service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os
import sys

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

from byoda.util.logger import Logger

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

    _LOGGER.debug(
        f'Starting service refresh worker for service ID: {service.service_id}'
    )

    metrics: dict[str, Counter | Gauge] = config.metrics

    wait_time: float = 0.0
    while True:
        if wait_time:
            _LOGGER.debug(f'Sleeping for {wait_time} seconds')
            await sleep(wait_time)

        edge: Edge | None = None
        try:
            metrics['svc_refresh_getting_oldest_asset'].inc()
            edge = await asset_cache.get_oldest_asset()
        except Exception as exc:
            _LOGGER.debug(
                f'Failed to get oldest asset from the all_assets list: {exc}'
            )
            metrics['svc_refresh_getting_oldest_asset_failures'].inc()
            # Double wait time to at least 1 but do not exceed MAX_WAIT
            wait_time = min(wait_time * 2, MAX_WAIT)
            wait_time = max(wait_time, 1)
            continue

        if not edge:
            _LOGGER.debug('No assets to refresh')
            metrics['svc_refresh_no_assets_available_at_all'].inc()
            wait_time = min(wait_time * 2, MAX_WAIT)
            wait_time = max(wait_time, 1)
            continue

        expires_in: float = await asset_cache.get_asset_expiration(edge)
        wait_time = expires_in

        metrics['svc_refresh_assets_oldest_asset_expires_in'].set(expires_in)
        if expires_in > CACHE_STALE_THRESHOLD:
            _LOGGER.debug(
                'No assets need to be refreshed as the oldest asset '
                f'{edge.node.asset_id} expires in {expires_in} seconds'
            )
            await asset_cache.add_oldest_asset(edge)

            continue

        try:
            _LOGGER.debug(
                f'We need to refresh asset {edge.node.asset_id} '
                f'from member {edge.origin}, expires in {expires_in} seconds'
            )
            metrics['svc_refresh_assets_needing'].inc()
            await asset_cache.refresh_asset(
                edge, ASSET_CLASS, service.tls_secret
            )
            metrics['svc_refresh_assets_runs'].inc()
            if not await asset_cache.add_newest_asset(edge):
                _LOGGER.debug('Failed to store asset in cache')
                metrics['svc_refresh_assets_failures'].labels(
                    member_id=edge.origin
                ).inc()
        except Exception as exc:
            # Currently, we do not put the asset back in the list
            # if the refresh fails. TODO: have 'retry' lists
            # to process failed refreshes
            _LOGGER.debug(
                f'Failed to refresh asset {edge.node.asset_id} '
                f'from member {edge.origin}: {exc}'
            )
            metrics['svc_refresh_assets_failures'].labels(
                member_id=edge.origin
            ).inc()


async def setup_server() -> tuple[Service, ServiceServer]:
    server_config = ServerConfig('svcserver', is_worker=True)
    server_config.logfile = '/var/log/byoda/worker-16384-refresh-assets.log'
    verbose: bool = \
        not server_config.debug and server_config.loglevel == 'INFO'

    global _LOGGER
    _LOGGER = Logger.getLogger(
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

    setup_exporter_metrics()

    listen_port: int = os.environ.get(
        'WORKER_METRICS_PORT', PROMETHEUS_EXPORTER_PORT
    )
#        server_config.listen_port or PROMETHEUS_EXPORTER_PORT
#    )

    start_http_server(listen_port)

    _LOGGER.debug(
        'Setup service server completed, now loading network secrets'
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

    await server.setup_asset_cache(server_config.server_config['asset_cache'])

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
        )
    }


if __name__ == '__main__':
    run(main)
