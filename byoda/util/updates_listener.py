'''
Listen to updates and persist the updates

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from copy import copy
from uuid import UUID
from uuid import uuid4
from typing import Self
from random import random
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from asyncio import CancelledError
from socket import gaierror as socket_gaierror

import orjson

from anyio import sleep
from anyio.abc import TaskGroup

from websockets.exceptions import ConnectionClosedError
from websockets.exceptions import WebSocketException
from websockets.exceptions import ConnectionClosedOK

from prometheus_client import Counter
from prometheus_client import Gauge

from byoda.datamodel.memberdata import EdgeResponse as Edge

from byoda.datamodel.network import Network
from byoda.datamodel.member import Member

from byoda.models.data_api_models import UpdatesResponseModel
from byoda.models.data_api_models import QueryResponseModel

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType
from byoda.datatypes import IngestStatus

from byoda.secrets.secret import Secret

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.datacache.asset_cache import AssetCache
from byoda.datacache.channel_cache import ChannelCache

from byoda.datacache.kv_cache import KVCache

from byoda.util.api_client.data_wsapi_client import DataWsApiClient

from byoda.requestauth.jwt import JWT

from byoda.util.test_tooling import is_test_uuid

from byoda.util.logger import Logger

from byoda.exceptions import ByodaRuntimeError

from byoda import config

_LOGGER: Logger = getLogger(__name__)


class UpdatesListener:
    # The maximum interval between attempts to reconnect to a member
    MAX_RECONNECT_DELAY: int = 3600
    # After how many days do we give up trying to connect to a dead member?
    MAX_DEAD_TIMER: int = 30

    '''
    Listen for updates to a class from a remote pod and store the updates
    in a cache
    '''

    def __init__(self, class_name: str, service_id: int,
                 remote_member_id: UUID, network_name: str,
                 tls_secret: Secret, annotations: list[str],
                 cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION,
                 max_asset_age: int = 0
                 ) -> None:
        '''
        Listen for updates to a class from a remote pod and store the updates
        in a cache

        :param class_name: the source data class for the data
        :param member_id: the member ID of the remote pod to listen to
        :param network_name: the name of the network that the pod is in
        :param tls_secret: our TLS secret of either our pod or service
        :param annotations: the annotations to use for filtering the data
        :param cache_expiration: the time in seconds after which the data
        should be expired
        :param max_asset_age: the age in seconds after which the asset should
        not be stored in the cache
        :returns: self
        '''

        self.log_extra: dict[str, str | UUID | int] = {
            'remote_member_id': remote_member_id,
            'service_id': service_id,
            'class_name': class_name,
            'network_name': network_name,
            'cache_expiration': cache_expiration
        }
        _LOGGER.debug(
            'Constructing UpdatesListener instance to member',
            extra=self.log_extra
        )

        self.class_name: str = class_name
        self.service_id: int = service_id
        self.remote_member_id: UUID = remote_member_id
        self.cache_expiration: int = cache_expiration
        self.network_name: str = network_name
        self.tls_secret: Secret = tls_secret
        self.annotations: list[str] = annotations
        self.max_asset_age: int = max_asset_age

    async def get_all_data(self) -> int:
        '''
        Gets all items of the data class of the remote member and
        stores them in the cache

        :returns: number of assets retrieved
        '''

        log_extra: dict[str, str | UUID | int] = copy(self.log_extra)
        _LOGGER.debug('Getting all assets from member', extra=log_extra)

        has_more_assets: bool = True
        first: int = 1000
        after: str | None = None
        assets_retrieved: int = 0

        metrics: dict[str, Gauge, Counter] = config.metrics
        sleepy_time: int = 0.1
        max_sleepy_time: int = 30
        while has_more_assets:
            log_extra['cursor'] = after
            log_extra['assets_retrieved'] = assets_retrieved
            log_extra['has_more_assets'] = has_more_assets
            metric: str
            try:
                resp: HttpResponse = await DataApiClient.call(
                    self.service_id, self.class_name, DataRequestType.QUERY,
                    secret=self.tls_secret, member_id=self.remote_member_id,
                    network=self.network_name, first=first, after=after,
                    timeout=10
                )
            except ByodaRuntimeError as exc:
                if sleepy_time < max_sleepy_time:
                    metric = 'failed_get_all_data_request_exception'
                    if metrics and 'metric' in metrics:
                        metrics['metric'].labels(
                            sleepy_time=sleepy_time,
                            member_id=self.remote_member_id
                        ).inc()
                    sleepy_time *= 2
                    await sleep(sleepy_time)
                    continue

                _LOGGER.debug(
                    'Exception while getting all assets from member',
                    extra=log_extra | {'exception': str(exc)}
                )
                metric = 'failed_get_all_data'
                if metrics and metric in metrics:
                    metrics[metric].labels(
                        member_id=self.remote_member_id
                    ).inc()
                return assets_retrieved

            if resp.status_code != 200:
                if sleepy_time < max_sleepy_time:
                    metric = 'failed_get_all_data_request_not_ok'
                    if metrics and metric in metrics:
                        metrics[metric].labels(
                            sleepy_time=sleepy_time,
                            status_code=resp.status_code,
                            member_id=self.remote_member_id
                        ).inc()
                    sleepy_time *= 2
                    log_extra['sleepy_time'] = sleepy_time
                    _LOGGER.debug(
                        'Failed to get all assets from member',
                        extra=log_extra | {
                            'http_status_code': resp.status_code
                        }
                    )
                    await sleep(sleepy_time)
                    continue

                _LOGGER.debug(
                    'Failed to get assets from member',
                    extra=log_extra | {
                        'http_status_code': resp.status_code,
                        'http_text': resp.text or 'empty response'
                    }
                )
                if metrics and 'failed_get_all_data' in metrics:
                    metrics['failed_get_all_data'].labels(
                        member_id=self.remote_member_id
                    ).inc()
                return assets_retrieved

            # We made it to here so we got data from the pod, so we can
            # reset the timer
            sleepy_time = 0.1
            log_extra['sleepy_time'] = sleepy_time

            data: list[dict[str, object]] = resp.json()

            try:
                response = QueryResponseModel(**data)
            except ValueError as exc:
                _LOGGER.info(
                    'Received corrupt data from member',
                    extra=log_extra | {'exception': str(exc)}
                )
                metric = 'updateslistener_received_corrupt_data'
                if metrics and metric in metrics:
                    metrics[metric].labels(
                        member_id=self.remote_member_id
                    ).inc()
                return assets_retrieved

            assets_retrieved += response.total_count
            log_extra['assets_retrieved'] = assets_retrieved

            _LOGGER.debug(
                'Received assets from request from member', extra=log_extra
            )
            metric = 'updateslistener_received_assets'
            if metrics and metric in metrics:
                metrics[metric].labels(
                    member_id=self.remote_member_id
                ).inc(assets_retrieved)

            edge: Edge
            for edge in response.edges or []:
                await self._process_asset_edge(edge, log_extra, metrics)

            has_more_assets: bool = response.page_info.has_next_page
            after: str = response.page_info.end_cursor

        _LOGGER.info(
            'Synced all assets from member', extra=self.log_extra | {
                'assets_retrieved': assets_retrieved
            }
        )
        metric = 'got_all_data_from_pod'
        if metrics and metric in metrics:
            metrics[metric].labels(member_id=self.remote_member_id).inc()

        self.log_extra['assets_retrieved'] = assets_retrieved
        return assets_retrieved

    async def _process_asset_edge(self, edge: Edge, log_extra: dict[str, any],
                                  metrics: dict[str, object]) -> bool:
        creator: str | None = edge.node.get('creator')
        ingest_status: str | None = edge.node.get('ingest_status')

        log_extra['creator'] = creator
        log_extra['ingest_status'] = ingest_status

        metric: str

        if ingest_status == IngestStatus.UNAVAILABLE.value:
            metric = 'asset_status_unavailable'
            if metrics and metric in metrics:
                metrics[metric].labels(member_id=self.remote_member_id).inc()
            return False

        # TODO: why do we need this check?
        if (self.annotations and isinstance(self.annotations, list)
                and creator not in self.annotations):
            _LOGGER.debug('Creator not in annotations', extra=log_extra)
            metric: str = 'creator_not_in_annotations'
            if metrics and metric in metrics:
                metrics[metric].labels(member_id=self.remote_member_id).inc()
            return False

        published_timestamp: float | int | datetime = edge.node.get(
            'published_timestamp'
        )
        if type(published_timestamp) in (float, int):
            published_timestamp = datetime.fromtimestamp(
                published_timestamp, tz=UTC
            )
        elif isinstance(published_timestamp, str):
            published_timestamp = datetime.fromisoformat(
                published_timestamp
            )

        log_extra['published_timestamp'] = published_timestamp
        log_extra['max_asset_age'] = self.max_asset_age

        now: datetime = datetime.now(tz=UTC)
        if self.max_asset_age and now - published_timestamp > timedelta(
                seconds=self.max_asset_age):
            _LOGGER.info('Skipping import of older asset', extra=log_extra)
            metric = 'asset_too_old_to_store_in_cache'
            if metrics and metric in metrics:
                metrics[metric].labels(member_id=self.remote_member_id).inc()
            return False

        _LOGGER.info(
            'Storing imported asset in cache', extra=log_extra
        )
        result: bool = await self.store_asset_in_cache(
            edge.node, edge.origin, edge.cursor
        )
        if result:
            if metrics:
                metric = 'updateslistener_assets_stored_in_cache'
                metrics[metric].labels(
                    member_id=self.remote_member_id,
                    ingest_status=ingest_status
                ).inc()
        else:
            _LOGGER.debug('Skipping import of asset', extra=log_extra)

        if metrics:
            metric = 'updateslistener_assets_skipped'
            metrics[metric].labels(member_id=self.remote_member_id).inc()

        return True

    async def setup_listen_assets(self, task_group: TaskGroup) -> None:
        '''
        Initiates listening for updates to a table (ie. 'public_assets') table
        of the member.

        :param task_group:
        :param member_id: the target member
        :param service: our own service
        :asset_db:
        :returns: (none)
        :raises: RuntimeError if we give up trying to connect to the remote
        '''

        _LOGGER.debug('Initiating listening to updates', extra=self.log_extra)

        task_group.start_soon(self.get_updates)

    async def get_updates(self) -> None:
        '''
        Listen to updates for a class from a remote pod and inject the updates
        into to the specified class in the local pod

        :param remote_member_id: the member ID of the remote pod to listen to
        :param class_name: the name of the data class to listen to updates for
        :param network_name: the name of the network that the pod is in
        :param member: the membership of the service in the local pod
        :param target_table: the table in the local pod where to store data
        :returns: (none)
        :raises: RuntimeError if we give up trying to connect to the remote
        '''

        service_id: int = self.service_id
        _LOGGER.debug(
            'Connecting to remote member for updates', extra=self.log_extra
        )

        metrics: dict[str, Gauge, Counter] | None = config.metrics
        metric: str = 'updateslistener_connection_retry_wait'
        if metrics and metric in metrics:
            metrics[metric].labels(member_id=self.remote_member_id).set(0)

        reconnect_delay: int = 0.5
        last_alive: datetime = datetime.now(tz=UTC)
        while True:
            metric: str = 'updateslistener_connection_healthy'
            if metrics and metric in metrics:
                metrics[metric].labels(member_id=self.remote_member_id).set(0)

            try:
                async for result in DataWsApiClient.call(
                        service_id, self.class_name, DataRequestType.UPDATES,
                        self.tls_secret, member_id=self.remote_member_id,
                        network=self.network_name
                ):
                    self.log_extra['reconnect_delay'] = reconnect_delay
                    updates_data: dict = orjson.loads(result)
                    try:
                        edge = UpdatesResponseModel(**updates_data)
                    except Exception as exc:
                        _LOGGER.debug(
                            'Received corrupt data from member',
                            extra=self.log_extra | {
                                'exception': str(exc),
                                'remote_member_id': self.remote_member_id
                            }
                        )
                        metric = 'updateslistener_received_corrupt_data'
                        if metrics and metric in metrics:
                            metrics[metric].labels(
                                member_id=self.remote_member_id
                            ).inc()
                        continue

                    self.log_extra['origin_id'] = edge.origin_id
                    self.log_extra['origin_id_type'] = edge.origin_id_type

                    if edge.origin_id_type != IdType.MEMBER:
                        _LOGGER.debug('Ignoring data', extra=self.log_extra)
                        continue

                    creator: str | None = edge.node['creator']
                    ingest_status: str | None = edge.node.get('ingest_status')
                    if (ingest_status != IngestStatus.UNAVAILABLE.value
                            and (not self.annotations
                                 or (isinstance(self.annotations, list)
                                     and creator in self.annotations))):
                        _LOGGER.debug(
                            'Appending data from member to asset cache',
                            extra=self.log_extra
                        )

                        result = await self.store_asset_in_cache(
                            edge.node, edge.origin_id, edge.cursor
                        )

                        metric = 'updateslistener_updates_received'
                        if result and metrics and metric in metrics:
                            metrics[metric].labels(
                                member_id=self.remote_member_id
                            ).inc()
                    else:
                        metric = 'updateslistener_assets_skipped'
                        if metrics and metric in metrics:
                            metrics[metric].labels(
                                member_id=self.remote_member_id
                            ).inc()

                    # We received data from the remote pod, so reset the
                    # reconnect delay
                    reconnect_delay = 0.2
                    last_alive = datetime.now(tz=UTC)
                    metric = 'updateslistener_connection_retry_wait'
                    if metrics and metric in metrics:
                        metrics[metric].labels(
                            member_id=self.remote_member_id
                        ).set(reconnect_delay)

                    # no need to sleep if we've been successful
                    continue
            except (ConnectionClosedOK, ConnectionClosedError,
                    WebSocketException, ConnectionRefusedError) as exc:
                _LOGGER.debug(
                    'Websocket client transport error. Will reconnect',
                    extra=self.log_extra | {'exception': str(exc)}
                )
                metric = 'updateslistener_websocket_client_transport_errors'
                if metrics and metric in metrics:
                    metrics[metric].labels(
                        member_id=self.remote_member_id
                        ).inc()
            except socket_gaierror as exc:
                _LOGGER.debug(
                    'Websocket connection to member failed',
                    extra=self.log_extra | {'exception': str(exc)}
                )
                metric = 'updateslistener_websocket_client_connection_errors'
                if metrics and metric in metrics:
                    metrics[metric].labels(
                        member_id=self.remote_member_id
                    ).inc()
            except CancelledError as exc:
                _LOGGER.debug(
                    'Websocket connection to member cancelled by asyncio',
                    extra=self.log_extra | {'exception': str(exc)}
                )
                metric = 'updateslistener_websocket_client_cancelled_errors'
                if metrics and metric in metrics:
                    metrics[metric].labels(
                        member_id=self.remote_member_id
                    ).inc()
            except Exception as exc:
                _LOGGER.debug(
                    'Failed to establish websocket connection',
                    extra=self.log_extra | {'exception': str(exc)}
                )
                metric = 'updateslistener_websocket_exception_errors'
                if metrics and metric in metrics:
                    metrics[metric].labels(
                        member_id=self.remote_member_id
                    ).inc()

            _LOGGER.debug('Websocket reconnect delay', extra=self.log_extra)

            metric: str = 'updateslistener_connection_healthy'
            if metrics and metric in metrics:
                metrics[metric].labels(member_id=self.remote_member_id).set(0)

            metric = 'updateslistener_connection_retry_wait'
            if metrics and metric in metrics:
                metrics[metric].labels(
                    member_id=self.remote_member_id
                ).set(reconnect_delay)
            await sleep(reconnect_delay)

            reconnect_delay += 2 * random() * reconnect_delay
            if reconnect_delay > UpdatesListener.MAX_RECONNECT_DELAY:
                reconnect_delay = UpdatesListener.MAX_RECONNECT_DELAY
            _LOGGER.debug(
                f'Reconnect delay is now {reconnect_delay}',
                extra=self.log_extra
            )

            not_seen_for: timedelta = \
                last_alive - datetime.now(tz=UTC)
            if not_seen_for > timedelta(days=3):
                _LOGGER.debug(
                    'Member not seen for 3 days', extra=self.log_extra
                )
                metric: str = 'updateslistener_expired_members'
                if metrics and metric in metrics:
                    metrics[metric].labels(
                        member_id=self.remote_member_id
                    ).inc()
                raise RuntimeError(
                    f'Member {self.remote_member_id} has not been seen for '
                    '3 days'
                )


class UpdateListenerService(UpdatesListener):
    def __init__(self, class_name: str, service_id: int, member_id: UUID,
                 network_name: str, tls_secret: Secret,
                 asset_cache: AssetCache, channel_cache: ChannelCache,
                 cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION,
                 max_asset_age: int = 0) -> Self:
        '''
        Constructor, do not call directly. Use UpdateListenerService.setup()

        :param data_class: class to retrieve data from
        :param member: the member to retrieve the data from
        :param asset_cache: the cache to store the data in
        :param target_lists: the lists to add the asset to
        :returns: self
        :raises: (none)
        '''

        super().__init__(
            class_name, service_id, member_id, network_name, tls_secret,
            cache_expiration, max_asset_age=max_asset_age
        )

        self.annotations: list[str] = []
        self.channel_cache: ChannelCache = channel_cache
        metrics: dict[str, Counter | Gauge] = config.metrics

        metric = 'updateslistener_members_seen'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of members already seen',
            )
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of members not yet seen',
            )

        metric = 'failed_get_all_data'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, (
                    'Failed to get all data from a member, '
                    'giving up on the member'
                ),
                ['member_id']
            )
        metric = 'failed_get_all_data_request_exception'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric,
                (
                    'Got a request exception while downloading '
                    'all data from a member'
                ),
                ['sleepy_time', 'member_id']
            )
        metric = 'failed_get_all_data_request_not_ok'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric,
                (
                    'Got a response other than HTTP 200 while downloading '
                    'all data from a member'
                ),
                ['sleepy_time', 'status_code', 'member_id']
            )

        metric: str = 'updateslistener_connection_healthy'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric, 'Health of a websocket connection to a member',
                ['member_id']
            )
        metric: str = 'updateslistener_connection_retry_wait'
        if metric not in metrics:
            metrics[metric] = Gauge(
                metric,
                (
                    'Time to wait before retrying to establish '
                    'a websocket connection to a member'
                ),
                ['member_id']
            )

        metric: str = 'updateslistener_expired_members'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of pods that we stopped asking for updates',
                ['member_id']
            )

        metric: str = 'updateslistener_received_corrupt_data'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of pods that returned corrupt data',
                ['member_id']
            )
        metric = 'updateslistener_updates_received'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of updates received', ['member_id']
            )

        metric = 'updateslistener_websocket_client_transport_errors'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of websocket client transport errors',
                ['member_id']
            )

        metric = 'updateslistener_websocket_client_connection_errors'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of websocket client connection errors',
                ['member_id']
            )

        metric = 'updateslistener_websocket_client_cancelled_errors'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of websocket client cancelled errors',
                ['member_id']
            )

        metric = 'updateslistener_websocket_exception_errors'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of unclassified websocket errors',
                ['member_id']
            )
        metric = 'updateslistener_received_assets'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of assets received from a member',
                ['member_id']
            )
        metric = 'updateslistener_assets_skipped'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric,
                (
                    'Number of assets not stored in cache because creator '
                    'not in annotations'
                ),
                ['member_id']
            )
        metric = 'updateslistener_received_assets_without_data'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of assets without data received from a member',
                ['member_id']
            )
        metric = 'updateslistener_assets_failed_to_store_in_cache'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of assets that could not be stored',
                ['member_id', 'ingest_status']
            )
        metric = 'updateslistener_assets_stored_in_cache'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Assets stored in cache',
                ['member_id', 'ingest_status']
            )

        metric = 'updateslistener_assets_seen'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of assets already seen by a listener',
                ['member_id']
            )

        metric = 'updateslistener_assets_unseen'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of assets not yet seen by a listener'
            )

        metric = 'asset_status_unavailable'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric, 'Number of assets with status=unavailable',
                ['member_id']
            )

        metric = 'creator_not_in_annotations'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric,
                'Number of assets with the creator not in the annotations',
                ['member_id']
            )

        metric = 'asset_too_old_to_store_in_cache'
        if metric not in metrics:
            metrics[metric] = Counter(
                metric,
                'Asset published_at is too old to store in cache',
                ['member_id']
            )

        self.asset_cache: AssetCache = asset_cache

    @staticmethod
    async def setup(class_name: str, service_id: int, member_id: UUID,
                    network_name: str, tls_secret: Secret,
                    asset_cache: AssetCache, channel_cache: ChannelCache,
                    cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION,
                    max_asset_age: int = 0) -> Self:
        '''
        Factory wrapper to enable async construction

        :param data_class: name of the class to retrieve data from
        :param member: the member to retrieve the data from
        :param asset_cache: the cache to store the data in
        :param target_lists: the lists to add the asset to
        :param exclude_false_values: the fields to check for False values,
        the value of the field in the data of an asset is False than that asset
        will not be stored in cache
        :returns: self
        :raises: (none)
        '''

        self = UpdateListenerService(
            class_name, service_id, member_id, network_name, tls_secret,
            asset_cache, channel_cache, cache_expiration, max_asset_age
        )

        return self

    def matches(self, member_id: UUID, service_id: int, source_class_name: str
                ) -> bool:
        '''
        Checks whether a listener matches the provided parameters
        '''

        seen: bool = (
            self.remote_member_id == member_id
            and self.service_id == service_id
            and self.class_name == source_class_name
        )

        metrics: dict[str, Counter | Gauge] = config.metrics
        if seen:
            metrics['updateslistener_members_seen'].inc()
        else:
            metrics['updateslistener_members_unseen'].inc()

    async def store_asset_in_cache(self, data: dict[str, object],
                                   origin_id: str, cursor: str) -> bool:
        '''
        Stores the asset in the AssetCache of the service

        :param data: the asset to store
        :param origin_id: the member_id originating the asset
        :param cursor: the cursor of the asset
        :returns: whether the data was stored successfully
        :raises: (none)
        '''

        metrics: dict[str, Counter | Gauge] = config.metrics
        if not data:
            _LOGGER.debug('Ignoring empty data', extra=self.log_extra)
            metric: str = 'updateslistener_received_assets_without_data'
            metrics[metric].labels(member_id=self.remote_member_id).inc()
            return False

        if is_test_uuid(data['asset_id']):
            if not data.get('video_thumbnails') or not data.get['title']:
                _LOGGER.debug(
                    'Not importing test asset without thumbnails',
                    extra=self.log_extra | {'asset_id': data['asset_id']}
                )
                return False

        ingest_status: str | None = data.get('ingest_status')
        log_extra: dict[str, str | UUID | int] = copy(self.log_extra)
        log_extra['ingest_status'] = ingest_status
        log_extra['origin_id'] = origin_id
        log_extra['cursor'] = cursor
        log_extra['asset_id'] = data['asset_id']
        if (ingest_status not in (IngestStatus.PUBLISHED.value,
                                  IngestStatus.EXTERNAL.value)):
            _LOGGER.debug(
                'Not importing asset for ingest_status', extra=self.log_extra
            )
            metrics['updateslistener_assets_failed_to_store_in_cache'].labels(
                member_id=self.remote_member_id, ingest_status=ingest_status
            ).inc()
            return False

        metrics: dict[str, Counter | Gauge] = config.metrics
        try:
            result: bool = await self.asset_cache.add_newest_asset(
                origin_id, data
            )
            if metrics:
                if result:
                    metrics['updateslistener_assets_stored_in_cache'].labels(
                        member_id=self.remote_member_id,
                        ingest_status=ingest_status
                    ).inc()
                else:
                    metric: str = \
                        'updateslistener_assets_failed_to_store_in_cache'
                    metrics[metric].labels(
                        member_id=self.remote_member_id,
                        ingest_status=ingest_status
                    ).inc()
        except Exception as exc:
            log_extra['exception'] = str(exc)
            _LOGGER.exception(
                'Failed to store asset in cache', extra=log_extra
            )
            return False

        self.channel_cache.append_channel(
            origin_id, {'creator': data['creator']}
        )
        return True


class UpdateListenerMember(UpdatesListener):
    '''
    Class to be used by a pod to listen to updates from a remote pod and
    store the data in its local cache.

    To store the data in the cache, the member calls its own Data API
    to store the data as that will not just store the date but also
    sends out the PubSub message for the /updates and /counters
    WebSocket APIs.
    '''

    def __init__(self, class_name: str, member: Member, remote_member_id: UUID,
                 dest_class_name: str, annotations: list[str],
                 cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION
                 ) -> Self:
        '''
        Constructor, do not call directly, use UpdateListenerMember.setup()

        :param data_class: class to retrieve data from
        :param member: the member to retrieve the data from
        :param dest_class_name: the class to store the data in
        :param annotations: the annotations to use for filtering the data
        :param cache_expiration: the time in seconds after which the data
        must be expired
        :returns: self
        :raises: (none)
        '''

        service_id: int = member.service_id
        network: Network = member.network
        network_name: str = network.name

        super().__init__(
            class_name, service_id, remote_member_id, network_name,
            member.tls_secret, annotations, cache_expiration
        )

        self.member: Member = member
        self.dest_class_name: str = dest_class_name

        # The JWT is used to call our own Data API to store the data
        # in the cache
        self.member_jwt: JWT = JWT.create(
                member.member_id, IdType.MEMBER, member.data_secret,
                member.network.name, member.service_id, IdType.MEMBER,
                member.member_id
        )

    def matches(self, member_id: UUID, service_id: int, source_class_name: str,
                dest_class_name: str) -> bool:
        '''
        Checks whether a listener matches the provided parameters
        '''

        return (
            self.remote_member_id == member_id
            and self.service_id == service_id
            and self.class_name == source_class_name
            and self.dest_class_name == dest_class_name
        )

    @staticmethod
    async def setup(class_name: str, member: Member, remote_member_id: UUID,
                    dest_class_name: str, annotations: list[str],
                    cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION,
                    ) -> Self:
        '''
        Factory

        :param data_class: class to retrieve data from
        :param member: our membership of the service
        :param remote_member_id: the member to retrieve the data from
        :param dest_class_name: the class to store the data in
        :param annotations: the annotations to use for filtering the data
        :param cache_expiration: the time in seconds after which the data
        must be expired
        :returns: self
        :raises: (none)
        '''

        self = UpdateListenerMember(
            class_name, member, remote_member_id, dest_class_name,
            annotations, cache_expiration,
        )
        _LOGGER.debug('Setting up listener as a member', extra=self.log_extra)

        return self

    async def store_asset_in_cache(self, data: dict[str, object],
                                   origin_id: str, _: str) -> bool:
        '''
        Stores the asset in the AssetCache of the service

        :param data: the asset to store
        :param origin_id: the member_id originating the asset
        :param cursor: the cursor of the asset
        :returns: whether the data was stored successfully
        :raises: (none)
        '''
        '''
        We call the Data API against the internal endpoint
        (http://127.0.0.1:8000) to ingest the data into the local
        pod as that will trigger the /updates WebSocket API to send
        the notifications

        :param data: data to store in the cache
        '''

        request_data: dict[str, object] = {
            'data': data,
            'origin_id': origin_id,
            'origin_id_type': IdType.MEMBER.value,
            'origin_class_name': self.class_name
        }

        # We set 'internal-True', which means this API call will
        # bypass the angie proxy and directly go to http://localhost:8000/
        query_id: UUID = uuid4()
        try:
            resp: HttpResponse = await DataApiClient.call(
                self.member.service_id, self.dest_class_name,
                DataRequestType.APPEND, member_id=self.member.member_id,
                data=request_data, headers=self.member_jwt.as_header(),
                query_id=query_id, internal=True
            )
        except ByodaRuntimeError as exc:
            _LOGGER.warning(
                'Got exception when appending video with query_id '
                f'{query_id}: {exc}', extra=self.log_extra
            )
            return False

        if resp.status_code != 200:
            _LOGGER.warning(
                f'Failed to append video with query_id {query_id}: '
                f'{resp.text or resp.status_code}', extra=self.log_extra
            )
            return False

        log_extra: dict[str, any] = copy(self.log_extra)
        log_extra['asset_id'] = data['asset_id']
        log_extra['ingest_status'] = data.get('ingest_status')
        log_extra['HTTP_status_code'] = resp.status_code
        _LOGGER.debug(
            'Successfully appended data', log_extra
        )

        return True
