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

import orjson

from anyio import run
from anyio import sleep

from httpx import ConnectError
from httpx import HTTPError

from prometheus_client import start_http_server
from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.datatypes import DataRequestType

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema
from byoda.datamodel.config import ServerConfig

from byoda.models.data_api_models import Channel
from byoda.models.data_api_models import EdgeResponse as Edge

from byoda.datacache.channel_cache import ChannelCache

from byoda.storage.filestorage import FileStorage

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.paths import Paths

from byoda.servers.service_server import ServiceServer

from byoda.util.logger import Logger

from byoda import config


# Time out waiting for a channel from the list of channels to
# get info from the pod
MAX_WAIT: int = 15 * 60

# Max time to wait before trying to refresh the next channel
MEMBER_PROCESS_INTERVAL: int = 8 * 60 * 60

CACHE_STALE_THRESHOLD: int = 4 * 60 * 60

ASSET_CLASS: str = 'channels'

PROMETHEUS_EXPORTER_PORT: int = 5000


async def main() -> None:
    service: Service
    server: ServiceServer
    metrics: dict[str, Counter | Gauge] = config.metrics
    service, server = await setup_server()

    _LOGGER.debug(
        f'Starting service worker for service ID: {service.service_id}'
    )

    channel_cache: ChannelCache = server.channel_cache

    wait_time: int = 0
    while True:
        if wait_time:
            _LOGGER.debug(f'Sleeping for {wait_time} seconds')
            await sleep(wait_time)

        try:
            edge: Edge[Channel] | None = \
                await channel_cache.get_oldest_channel()

            if not edge:
                _LOGGER.warning('No channel available in list of channels')
                metrics['svc_channels_no_channels_available'].inc()
                wait_time = 5
                continue

            if edge.expires_in > CACHE_STALE_THRESHOLD:
                wait_time = int(edge.expires_in - CACHE_STALE_THRESHOLD)
                _LOGGER.debug(
                    f'Next channel to become stale in {wait_time} seconds'
                )
                metrics['svc_channels_wait_for_stale_channel'].set(wait_time)
                await channel_cache.add_oldest_channel_back(edge)
                continue

            channel: Channel = edge.node
            metrics['svc_channels_channel_refresh_attempts'].inc()
            _LOGGER.debug(
                f'Processing channel {channel.creator} of member {edge.origin}'
            )
            wait_time = 0
            new_edge: Edge[Channel] = await get_channel_from_pod(edge)
            if new_edge:
                metrics['svc_channels_channels_refreshed'].inc()
                await channel_cache.add_newest_channel(new_edge)
            else:
                metrics['svc_channels_channel_no_longer_available'].inc()

        except Exception as exc:
            # We need to catch any exception to make sure we can try
            # adding the member_id back to the list of member_ids in the
            # MemberDb
            _LOGGER.exception(f'Got exception: {exc}')
            wait_time = min(wait_time * 2, MAX_WAIT)


async def get_channel_from_pod(edge: Edge[Channel]) -> Edge[Channel] | None:
    service: Service = config.server.service
    metrics: dict[str, Counter | Gauge] = config.metrics

    channel: Channel = edge.node

    _LOGGER.debug(
        f'Getting channel {channel.creator} from pod of member {edge.origin}'
    )

    try:
        resp: HttpResponse = await DataApiClient.call(
            service.service_id, ASSET_CLASS, DataRequestType.QUERY,
            member_id=edge.origin, filter={'creator': {'eq': channel.creator}},
            network=service.network.name
        )

        if resp.status_code != 200:
            _LOGGER.error(
                f'Failed to get channel {channel.creator} '
                f'from member {edge.origin}'
            )
            return None

        metric: str = 'svc_channels_fetched'
        metrics[metric].inc()

        edge_data: dict[str, any] = orjson.loads(resp.json())

        new_edge: Edge[Channel] = Edge(
            origin=edge.origin, node=edge_data['channel'], cursor=edge.cursor
        )
        return new_edge
    except (ConnectError, HTTPError) as exc:
        _LOGGER.error(
            f'Failed to get channel {channel.creator} '
            f'from pod of member {edge.origin}: {exc}'
        )
        return None
    except Exception as exc:
        _LOGGER.exception(f'Got exception: {exc}')
        return None


async def setup_server() -> tuple[Service, ServiceServer]:
    server_config = ServerConfig('svcserver', is_worker=True)
    server_config.logfile = '/var/log/byoda/worker-16384-channel-refresh.log'

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

    await server.setup_channel_cache(
        server_config.server_config['asset_cache'],
        server_config.server_config['asset_cache_readwrite']
    )

    return service, server


def setup_exporter_metrics() -> None:
    metrics: dict[str, Counter | Gauge] = config.metrics

    metric: str = 'svc_channels_no_channels_available'
    if metric not in metrics:
        metrics[metric] = Gauge(
            metric, 'Did not get channel from list of channels'
        )

    metric = 'svc_channels_wait_for_stale_channel'
    if metric not in metrics:
        metrics[metric] = Gauge(
            metric, 'Time before next channel becomes stale'
        )

    metric = 'svc_channels_channel_refresh_attempts'
    if metric not in metrics:
        metrics[metric] = Gauge(
            metric, 'Number of channel refresh runs'
        )

    metric = 'svc_channels_channel_no_longer_available'
    if metric not in metrics:
        metrics[metric] = Gauge(
            metric, 'Channels no longer available'
        )


if __name__ == '__main__':
    run(main)
