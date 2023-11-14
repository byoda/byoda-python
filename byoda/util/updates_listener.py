'''
Listen to updates and persist the updates

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

from uuid import UUID
from uuid import uuid4
from typing import Self
from random import random
from logging import getLogger
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from asyncio import CancelledError
from socket import gaierror as socket_gaierror

import orjson

from anyio import sleep
from anyio.abc import TaskGroup

from websockets.exceptions import ConnectionClosedError
from websockets.exceptions import WebSocketException
from websockets.exceptions import ConnectionClosedOK

from byoda.datamodel.network import Network
from byoda.datamodel.member import Member

from byoda.models.data_api_models import UpdatesResponseModel
from byoda.models.data_api_models import QueryResponseModel

from byoda.datatypes import IdType
from byoda.datatypes import DataRequestType

from byoda.secrets.secret import Secret

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.datacache.asset_cache import AssetCache

from byoda.datacache.kv_cache import KVCache

from byoda.util.api_client.data_wsapi_client import DataWsApiClient

from byoda.requestauth.jwt import JWT

from byoda.util.logger import Logger

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
                 remote_member_id: UUID, network_name: str, tls_secret: Secret,
                 cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION
                 ) -> Self:
        '''
        Listen for updates to a class from a remote pod and store the updates
        in a cache

        :param class_name: the source data class for the data
        :param member_id: the member ID of the remote pod to listen to
        :param network_name: the name of the network that the pod is in
        :param tls_secret: our TLS secret of either our pod or service
        :param cache_expiry: the time in seconds after which the data should
        be expired
        :returns: self
        '''

        self.class_name: str = class_name
        self.service_id: int = service_id
        self.remote_member_id: UUID = remote_member_id
        self.cache_expiration: int = cache_expiration
        self.network_name: str = network_name
        self.tls_secret: Secret = tls_secret

    async def get_all_data(self) -> int:
        '''
        Gets all items of the data class of the remote member and
        stores them in the cache

        :returns: number of assets retrieved
        '''

        has_more_assets: bool = True
        first: int = 100
        after: str | None = None
        assets_retrieved: int = 0

        while has_more_assets:
            resp: HttpResponse = await DataApiClient.call(
                self.service_id, self.class_name, DataRequestType.QUERY,
                secret=self.tls_secret, member_id=self.remote_member_id,
                network=self.network_name, first=first, after=after,
            )
            if resp.status_code != 200:
                _LOGGER.debug(
                    f'Failed to get assets from member '
                    f'{self.remote_member_id}: '
                    f'{resp.status_code}: {resp.text}'
                )
                return assets_retrieved

            data: list[dict[str, object]] = resp.json()

            try:
                response = QueryResponseModel(**data)
            except ValueError as exc:
                _LOGGER.debug(
                    'Received corrupt data '
                    f'from member {self.remote_member_id}: {exc}'
                )
                return assets_retrieved

            assets_retrieved += response.total_count
            _LOGGER.debug(
                f'Received {response.total_count} assets from request from '
                f'member {self.remote_member_id}, total is now '
                f'{assets_retrieved}'
            )

            for edge in response.edges or []:
                await self.store_asset_in_cache(
                    edge.node, edge.origin, edge.cursor
                )

            has_more_assets: bool = response.page_info.has_next_page
            after: str = response.page_info.end_cursor

        _LOGGER.debug(
            f'Synced {assets_retrieved} assets '
            f'from {self.remote_member_id}'
        )

        return assets_retrieved

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

        _LOGGER.debug(
            f'Initiating listening to updates for class {self.class_name} '
            f'of member {self.remote_member_id}'
        )

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
            f'Connecting to remote member {self.remote_member_id} for updates '
            f'to class {self.class_name} of service {self.service_id}'
        )

        # Aggressive retry as we're talking to our own pod
        reconnect_delay: int = 0.2
        last_alive = datetime.now(tz=timezone.utc)
        while True:
            try:
                async for result in DataWsApiClient.call(
                        service_id, self.class_name, DataRequestType.UPDATES,
                        self.tls_secret, member_id=self.remote_member_id,
                        network=self.network_name
                ):
                    updates_data: dict = orjson.loads(result)
                    edge = UpdatesResponseModel(**updates_data)
                    _LOGGER.debug(
                        f'Appending data from class {self.class_name} '
                        f'originating from {edge.origin_id} '
                        f'received from member {self.remote_member_id}'
                        f'to asset cache: {edge.node}'
                    )

                    if edge.origin_id_type != IdType.MEMBER:
                        _LOGGER.debug(
                            f'Ignoring data from {edge.origin_id_type.value} '
                            f'{edge.origin_id}'
                        )
                        continue

                    await self.store_asset_in_cache(
                        edge.node, edge.origin_id, None
                    )

                    # We received data from the remote pod, so reset the
                    # reconnect # delay
                    reconnect_delay = 0.2
                    last_alive = datetime.now(tz=timezone.utc)
            except (ConnectionClosedOK, ConnectionClosedError,
                    WebSocketException, ConnectionRefusedError) as exc:
                _LOGGER.debug(
                    f'Websocket client transport error to '
                    f'{self.remote_member_id}. Will reconnect '
                    f'in {reconnect_delay} secs: {exc}'
                )
            except socket_gaierror as exc:
                _LOGGER.debug(
                    f'Websocket connection to member {self.remote_member_id} '
                    f'failed: {exc}'
                )
            except CancelledError as exc:
                _LOGGER.debug(
                    f'Websocket connection to member {self.remote_member_id} '
                    f'cancelled by asyncio: {exc}'
                )
            except Exception as exc:
                _LOGGER.debug(
                    f'Failed to establish connection '
                    f'to {self.remote_member_id}: {exc}'
                )

            await sleep(reconnect_delay)

            reconnect_delay += 2 * random() * reconnect_delay
            if reconnect_delay > UpdatesListener.MAX_RECONNECT_DELAY:
                reconnect_delay = UpdatesListener.MAX_RECONNECT_DELAY

            if last_alive - datetime.now(tz=timezone.utc) > timedelta(days=30):
                raise RuntimeError(
                    f'Member {self.remote_member_id} has not been seen for '
                    '30 days'
                )


class UpdateListenerService(UpdatesListener):
    def __init__(self, class_name: str, service_id: int, member_id: UUID,
                 network_name: str, tls_secret: Secret,
                 asset_cache: AssetCache, target_lists: set[str],
                 cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION
                 ) -> Self:
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
            cache_expiration
        )

        self.asset_cache: AssetCache = asset_cache
        self.target_lists: set[str] = target_lists

    def matches(self, member_id: UUID, service_id: int, source_class_name: str
                ) -> bool:
        '''
        Checks whether a listener matches the provided parameters
        '''

        return (
            self.remote_member_id == member_id
            and self.service_id == service_id
            and self.class_name == source_class_name
        )

    async def setup(class_name: str, service_id: int, member_id: UUID,
                    network_name: str, tls_secret: Secret,
                    asset_cache: AssetCache, target_lists: set[str],
                    cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION
                    ) -> Self:
        '''
        Factory

        :param data_class: class to retrieve data from
        :param member: the member to retrieve the data from
        :param asset_cache: the cache to store the data in
        :param target_lists: the lists to add the asset to
        :returns: self
        :raises: (none)
        '''

        self = UpdateListenerService(
            class_name, service_id, member_id, network_name, tls_secret,
            asset_cache, target_lists, cache_expiration
        )
        target_list: str
        for target_list in self.target_lists:
            if not await self.asset_cache.exists_list(target_list):
                await self.asset_cache.create_list(target_list)

        return self

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

        for dest_class_name in self.target_lists:
            _LOGGER.debug(
                f'Adding asset {data["asset_id"]} from member {origin_id} '
                f'to list {dest_class_name}'
            )
            await self.asset_cache.lpush(
                dest_class_name, data, origin_id, cursor
            )


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
                 dest_class_name: str,
                 cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION
                 ) -> Self:
        '''
        Constructor, do not call directly, use UpdateListenerMember.setup()

        :param data_class: class to retrieve data from
        :param member: the member to retrieve the data from
        :param dest_class_name: the class to store the data in
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
            member.tls_secret, cache_expiration
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

    async def setup(class_name: str, member: Member, remote_member_id: UUID,
                    dest_class_name: str,
                    cache_expiration: int = KVCache.DEFAULT_CACHE_EXPIRATION
                    ) -> Self:
        '''
        Factory

        :param data_class: class to retrieve data from
        :param member: our membership of the service
        :param remote_member_id: the member to retrieve the data from
        :param dest_class_name: the class to store the data in
        :param cache_expiration: the time in seconds after which the data
        must be expired
        :returns: self
        :raises: (none)
        '''

        self = UpdateListenerMember(
            class_name, member, remote_member_id, dest_class_name,
            cache_expiration
        )

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
        # bypass the nginx proxy and directly go to http://localhost:8000/
        query_id: UUID = uuid4()
        resp: HttpResponse = await DataApiClient.call(
            self.member.service_id, self.dest_class_name,
            DataRequestType.APPEND, member_id=self.member.member_id,
            data=request_data, headers=self.member_jwt.as_header(),
            query_id=query_id, internal=True
        )

        if resp.status_code != 200:
            _LOGGER.warning(
                f'Failed to append video {data.get("asset_id")} '
                f'to class {self.dest_class_name} '
                f'with query_id {query_id}: {resp.status_code}'
            )
            return False

        _LOGGER.debug(
            f'Successfully appended data: {resp.status_code}'
        )

        return True
