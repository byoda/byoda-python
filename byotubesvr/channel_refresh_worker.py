#!/usr/bin/python3

'''
Worker that performs queries against registered members of
the service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2024
:license    : GPLv3
'''

import os
import sys

from datetime import UTC
from datetime import datetime

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
    server: ServiceServer
    metrics: dict[str, Counter | Gauge] = config.metrics

    server = await setup_server()
    service: Service = server.service

    _LOGGER.debug(
        f'Starting channel refresh worker for service ID: {service.service_id}'
    )

    channel_cache: ChannelCache = server.channel_cache_readwrite

    wait_time: int = 0
    while True:
        if wait_time:
            _LOGGER.debug(f'Sleeping for {wait_time} seconds')
            await sleep(wait_time)

        try:
            edge: Edge[Channel] | None = \
                await channel_cache.get_oldest_channel()

            if not edge:
                wait_time = 5
                _LOGGER.warning(
                    'No channel available in list of channels, '
                    f'waiting {wait_time} seconds'
                )
                metrics['svc_channels_no_channels_available'].inc()
                continue
        except Exception as exc:
            # We need to catch any exception to make sure we can try
            # adding the member_id back to the list of member_ids in the
            # MemberDb
            _LOGGER.exception(f'Got exception: {exc}')
            wait_time = min(wait_time * 2, MAX_WAIT)
            continue

        channel: Channel = edge.node
        now = int(datetime.now(tz=UTC).timestamp())

        stale_in: int = 0
        if edge.expires_at:
            stale_at: int = edge.expires_at - CACHE_STALE_THRESHOLD
            stale_in: int = stale_at - now

        if stale_in > 0:
            wait_time = stale_in
            _LOGGER.debug(
                f'Next channel to become stale in {wait_time} seconds'
            )
            metrics['svc_channels_wait_for_stale_channel'].set(wait_time)
            await channel_cache.add_oldest_channel_back(edge.origin, channel)
            continue

        metrics['svc_channels_channel_refresh_attempts'].inc()
        _LOGGER.debug(
            f'Processing channel {channel.creator} of member {edge.origin}'
        )
        wait_time = 0
        try:
            new_edge: Edge[Channel] = await get_channel_from_pod(edge)
            if new_edge:
                metrics['svc_channels_channels_refreshed'].inc()
                _LOGGER.debug(
                    f'Adding channel {channel.creator} back as newest channel'
                )
                await channel_cache.add_newest_channel(
                    new_edge.origin, new_edge.node
                )
            else:
                metrics['svc_channels_channel_no_longer_available'].inc()
                _LOGGER.debug('Did not receive a new edge for the channel')
                # TODO: for now we just add the channel back. Need to
                # have retry lists for channels that can't be renewed
                # because of connectivity issues
                await channel_cache.add_oldest_channel_back(
                    edge.origin, channel
                )

            continue
        except Exception as exc:
            # We need to catch any exception to make sure we can try
            # adding the member_id back to the list of member_ids in the
            # MemberDb
            _LOGGER.exception(f'Got exception: {exc}')
            if not wait_time:
                wait_time = 1
            else:
                wait_time = min(wait_time * 2, MAX_WAIT)

        try:
            await channel_cache.add_oldest_channel_back(edge)
        except Exception as exc:
            _LOGGER.exception(f'Could not add oldest channel back: {exc}')


async def get_channel_from_pod(edge: Edge[Channel]) -> Edge[Channel] | None:
    service: Service = config.server.service
    network: Network = service.network
    metrics: dict[str, Counter | Gauge] = config.metrics

    channel: Channel = edge.node

    _LOGGER.debug(
        f'Getting channel {channel.creator} from pod of member {edge.origin}'
    )

    try:
        resp: HttpResponse = await DataApiClient.call(
            service.service_id, ASSET_CLASS, DataRequestType.QUERY,
            member_id=edge.origin, network=network.name,
            data_filter={'creator': {'eq': channel.creator}},
        )

        if resp.status_code != 200:
            _LOGGER.error(
                f'Failed to get channel {channel.creator} '
                f'from member {edge.origin}'
            )
            return None

        metrics['svc_channels_channels_fetched'].inc()

        data: dict[str, any] = resp.json()
        if not data or not isinstance(data, dict) or not data.get('edges'):
            _LOGGER.info(
                f'No data returned for channel {channel.creator} '
                f'from member {edge.origin}'
            )
            return None

        edges: list[dict[str, any]] = data.get('edges')
        if not isinstance(edges, list) or not len(edges):
            _LOGGER.info(
                'No edges included in data returned for channel '
                f'{channel.creator} from member {edge.origin}'
            )
            return None

        node: dict[str, any] = edges[0].get('node')
        if not node or not isinstance(node, dict) or 'creator' not in node:
            _LOGGER.info(
                f'No node data returned for channel {channel.creator} '
                f'from member {edge.origin}'
            )
            return None

        new_creator: str = node['creator']
        if not new_creator:
            _LOGGER.info(
                f'No creator returned for channel {channel.creator} '
                f'from member {edge.origin}'
            )
            return None

        _LOGGER.debug('Preparing data structure for updated channel')
        new_channel: Channel = Channel(**node)
        new_edge: Edge[Channel] = Edge(
            origin=edge.origin, node=new_channel, cursor=edge.cursor
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
    server_config.logfile = \
        server_config.server_config['channel_refresh_worker_logfile']

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

    await server.setup_channel_cache(
        server_config.server_config['asset_cache'],
        server_config.server_config['asset_cache_readwrite']
    )

    return server


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

    metric = 'svc_channels_channels_fetched'
    if metric not in metrics:
        metrics[metric] = Counter(
            metric, 'Number of channels fetched from pods'
        )

    metric = 'svc_channels_channels_refreshed'
    if metric not in metrics:
        metrics[metric] = Gauge(
            metric, 'Channels no longer available'
        )

    metric = 'svc_channels_channel_no_longer_available'
    if metric not in metrics:
        metrics[metric] = Gauge(
            metric, 'Channels no longer available'
        )


if __name__ == '__main__':
    run(main)
