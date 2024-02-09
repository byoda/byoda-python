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

from uuid import UUID
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import orjson

from datetime import UTC

from anyio import run
from anyio import sleep
from anyio import create_task_group
from anyio.abc import TaskGroup

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

from byoda.models.data_api_models import EdgeResponse as Edge

from byoda.datastore.memberdb import MemberDb

from byoda.storage.filestorage import FileStorage

from byoda.util.updates_listener import UpdateListenerService

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.paths import Paths

from byoda.secrets.service_secret import ServiceSecret

from byoda.servers.service_server import ServiceServer

from byoda.exceptions import ByodaRuntimeError

from byoda.util.logger import Logger

from byoda.util.test_tooling import is_test_uuid

from byoda import config

from byoda.datacache.asset_cache import AssetCache

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

# Time out waiting for a member from the list of members to
# get info from the Person table
MAX_WAIT: int = 15 * 60

# Max time to wait before connecting to the next member again
# to get info from the Person table
MEMBER_PROCESS_INTERVAL: int = 8 * 60 * 60

CACHE_STALE_THRESHOLD: int = 4 * 60 * 60

ASSET_CLASS: str = 'public_assets'

PROMETHEUS_EXPORTER_PORT: int = 5000


async def main() -> None:
    service: Service
    server: ServiceServer

    service, server = await setup_server()

    _LOGGER.debug(
        f'Starting service worker for service ID: {service.service_id}'
    )

    member_db: MemberDb = server.member_db
    wait_time: float = 0.0
    members_seen: dict[UUID, UpdateListenerService] = {}

    async with create_task_group() as task_group:
        # Set up the listeners for the members that are already in the cache
        _LOGGER.debug('Start up member reconsilation')
        await reconcile_member_listeners(
            member_db, members_seen, service, ASSET_CLASS, server.asset_cache,
            task_group
        )
        while True:
            _LOGGER.debug(f'Members seen: {len(members_seen)}')
            if wait_time:
                await refresh_assets(
                    wait_time, service.tls_secret, server.asset_cache
                )

            wait_time = MAX_WAIT

            member_id: UUID | None = None
            try:
                member_id = await member_db.get_next(timeout=MAX_WAIT)
                if not member_id:
                    _LOGGER.debug('No member available in list of members')
                    continue

                if is_test_uuid(member_id):
                    _LOGGER.debug(
                        f'Not processing member with test UUID: {member_id}'
                    )
                    continue

                _LOGGER.debug(f'Processing member_id {member_id}')

                _LOGGER.debug(f'Members seen: {len(members_seen)}')
                await reconcile_member_listeners(
                    member_db, members_seen, service, ASSET_CLASS,
                    server.asset_cache, task_group
                )

                # TODO: develop logic to figure out what data to collect
                # for each service without hardcoding
                if service.service_id == ADDRESSBOOK_SERVICE_ID:
                    wait_time = await update_member(
                        service, member_id, server.member_db
                    )
            except Exception as exc:
                # We need to catch any exception to make sure we can try
                # adding the member_id back to the list of member_ids in the
                # MemberDb
                _LOGGER.exception(f'Got exception: {exc}')

            if not wait_time:
                wait_time = 0.1
            elif member_id:
                # Add the member back to the list of members as it seems
                # to be up and running, even if it may not have returned
                # any data
                _LOGGER.debug(f'Adding {member_id} back to the list')
                await member_db.add_member(member_id)


async def refresh_assets(time_available: int, tls_secret: ServiceSecret,
                         asset_cache: AssetCache) -> None:
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

    now: float = datetime.now(tz=UTC).timestamp()

    metrics: dict[str, Counter | Gauge] = config.metrics

    _LOGGER.debug(f'Got {time_available} seconds to refresh stale assets')
    end_time: float = now + time_available
    edge: Edge | None = None
    while now < end_time:
        try:
            edge = await asset_cache.get_oldest_asset()
        except Exception as exc:
            _LOGGER.debug(
                f'Failed to get oldest asset from the all_assets list: {exc}'
            )

        if not edge:
            _LOGGER.debug('No assets to refresh')
            metrics['svcworker_no_assets_available_at_all'].inc()
            break

        expires_in: float = await asset_cache.get_asset_expiration(edge)
        metrics['svcworker_oldest_asset_expires_in'].set(expires_in)
        if expires_in > CACHE_STALE_THRESHOLD:
            _LOGGER.debug(
                'No assets need to be refreshed as the oldest asset '
                f'{edge.node.asset_id} expires in {expires_in} seconds'
            )
            await asset_cache.add_oldest_asset(edge)
            break

        try:
            _LOGGER.debug(
                f'We need to referesh asset {edge.node.asset_id} '
                f'from member {edge.origin}, expires in {expires_in} seconds'
            )
            metrics['svcworker_assets_needing_refresh'].inc()
            await asset_cache.refresh_asset(edge, ASSET_CLASS, tls_secret)
            metrics['svcworker_refresh_asset_runs'].inc()
        except Exception as exc:
            _LOGGER.debug(
                f'Failed to refresh asset {edge.node.asset_id} '
                f'from member {edge.origin}: {exc}'
            )

    sleep_period: float = end_time - datetime.now(tz=UTC).timestamp()
    metrics['svcworker_idle_time'].set(sleep_period)
    _LOGGER.debug('No time to sleep')
    if sleep_period > 0:
        _LOGGER.debug(
            f'Sleeping {sleep_period} seconds until next refresh period'
        )
        await sleep(sleep_period)


async def reconcile_member_listeners(
        member_db: MemberDb, members_seen: dict[UUID, UpdateListenerService],
        service: Service, asset_class_name: str, asset_cache: AssetCache,
        task_group: TaskGroup) -> None:
    '''
    Sets up asset sync and listener for members not seen before.

    This function updates the 'members_seen' parameter

    :param member_db:
    :param members_seen: members that we are already listening to
    :param service: the service for which to listen to updates to
    :param asset_class: the data class to listen for updates to
    :param asset_cache: the cache to use for the asset
    :param task_group: the anyio task group to use for the listener
    :return: (none)
    '''

    member_ids: list[UUID] = await member_db.get_members()
    _LOGGER.debug(
        f'Reconciling member listeners (currently {len(members_seen)}) '
        f'with members (currently {len(member_ids)})'
    )

    metrics: dict[str, Counter | Gauge] = config.metrics
    metrics['svcworker_total_members'].set(len(member_ids))

    unseen_members: list[UUID] = [
        m_id for m_id in member_ids
        if m_id not in members_seen and not is_test_uuid(m_id)
    ]
    _LOGGER.debug(
        f'Seen members: {len(members_seen)}, '
        f'Unseen members: {len(unseen_members)}'
    )

    metrics['svcworker_unseen_members'].set(len(unseen_members))

    network: Network = service.network
    member_id: UUID
    for member_id in unseen_members:
        _LOGGER.debug(f'Adding new {member_id} to list of members')

        listener: UpdateListenerService = await UpdateListenerService.setup(
            asset_class_name, service.service_id, member_id,
            network.name, service.tls_secret, asset_cache
        )

        _LOGGER.debug(f'Initiating sync and listener for member {member_id}')
        await listener.get_all_data()
        await listener.setup_listen_assets(task_group)

        members_seen[member_id] = listener
        metrics['svcworker_total_members'].inc()


async def update_member(service: Service, member_id: UUID, member_db: MemberDb
                        ) -> int | None:
    '''
    This code runs for the addressbook test service, collecting information
    about members and making it searchable.
    '''

    try:
        data: dict[str, any] = await member_db.get_meta(member_id)
    except TypeError as exc:
        _LOGGER.exception(f'Invalid data for member: {member_id}: {exc}')
        return None
    except KeyError as exc:
        _LOGGER.info(f'Member not found: {member_id}: {exc}')
        return None

    await member_db.add_meta(
        data['member_id'], data['remote_addr'], data['schema_version'],
        data['data_secret'], data['status']
    )

    wait_time: int = next_member_wait(data['last_seen'])

    #
    # Here is where we can do stuff
    #
    try:
        await update_member_info(service, member_db, member_id)

    except (HTTPError, ConnectError, ByodaRuntimeError) as exc:
        _LOGGER.info(
            f'Not adding member back to the list because we failed '
            f'to get data from member: {member_id}: {exc}'
        )
        return None

    return wait_time


async def update_member_info(service: Service, member_db: MemberDb,
                             member_id: UUID) -> None:
    '''
    Updates the info about a member of the service so that we
    can support searches based on email address of the member

    :param service: our service
    :param meber_db: where to store the data
    :param member_id: the member to update
    :returns: (none)
    :raises: (none)
    '''

    if service.service_id == ADDRESSBOOK_SERVICE_ID:
        resp: HttpResponse = await DataApiClient.call(
            service.service_id, 'person', DataRequestType.QUERY,
            secret=service.tls_secret, member_id=member_id
        )

        body: dict[list[dict[str, any]]] = resp.json()

        edges: list[dict[str, any]] = body['edges']
        if not edges:
            _LOGGER.debug(f'Did not get any info from the pod: {body}')
        else:
            person_data: dict[str, any] = edges[0]['node']
            _LOGGER.info(
                f'Got data from member {member_id}: '
                f'{orjson.dumps(person_data)}'
            )
            await member_db.set_data(member_id, person_data)

            await member_db.kvcache.set(
                person_data['email'], str(member_id)
            )


def next_member_wait(last_seen: datetime) -> int:
    '''
    Calculate how long to wait before processing the next member
    in the list. We calculate using the last_seen time of the
    current member, knowing that it is always less than the wait
    time of the next member. So we're okay with processing the
    next member to early.

    :param last_seen: The last time the member was seen
    :return: number of seconds to sleep
    :raises: (none)
    '''

    now: datetime = datetime.now(timezone.utc)

    wait_time: datetime = (
        last_seen + timedelta(seconds=MEMBER_PROCESS_INTERVAL) - now
    )

    wait: int = max(0, min(wait_time.seconds, MAX_WAIT))

    return wait


async def setup_server() -> (Service, ServiceServer):
    server_config = ServerConfig('svcserver', is_worker=True)

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
        'WORKER_METRICS_PORT',
        server_config.listen_port or PROMETHEUS_EXPORTER_PORT
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

    await server.setup_asset_cache(server_config.server_config['asset_cache'])

    return service, server


def setup_exporter_metrics() -> None:
    config.metrics = {
        'svcworker_total_members': Gauge(
            'svcworker_total_members', 'Number of members in MemberDB'
        ),
        'svcworker_unseen_members': Gauge(
            'svcworker_unseen_members', 'Number of unseen members'
        ),
        'svcworker_idle_time': Gauge(
            'svcworker_idle_time', 'Time spent waiting for next refresh period'
        ),
        'svcworker_no_assets_available_at_all': Counter(
            'svcworker_no_assets_available_at_all',
            'number of times we did not have to run the refresh any assets'
        ),
        'svcworker_refresh_asset_runs': Counter(
            'svcworker_refresh_asset_runs',
            'number of times we had to run the refresh asset procedure'
        ),
        'svcworker_assets_needing_refresh': Counter(
            'svcworker_assets_needing_refresh',
            'Number of assets needing refresh'
        ),
        'svcworker_oldest_asset_expires_in': Gauge(
            'svcworker_oldest_asset_expires_in',
            'Seconds until the oldest asset expires'
        ),
    }


if __name__ == '__main__':
    run(main)
