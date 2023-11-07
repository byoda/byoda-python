#!/usr/bin/env python3

'''
Listen for updates of pods in the network and store them in the local pod

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license
'''

import os
import sys

from uuid import UUID
from uuid import uuid4
from random import random
from asyncio import CancelledError
from socket import gaierror as socket_gaierror

import orjson

from anyio import run
from anyio import sleep
from anyio import create_task_group
from anyio.abc import TaskGroup

from websockets.exceptions import ConnectionClosedError
from websockets.exceptions import WebSocketException
from websockets.exceptions import ConnectionClosedOK

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.schema import ListenRelation
from byoda.datamodel.pubsub_message import PubSubMessage
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.table import ResultData
from byoda.datamodel.table import QueryResult

from byoda.datatypes import DataRequestType
from byoda.datatypes import CloudType
from byoda.datatypes import MARKER_NETWORK_LINKS
from byoda.datatypes import IdType
from byoda.datatypes import PubSubMessageAction

from byoda.storage.pubsub_nng import PubSubNng

from byoda.datastore.data_store import DataStore
from byoda.datastore.data_store import DataStoreType
from byoda.datastore.cache_store import CacheStore
from byoda.datastore.cache_store import CacheStoreType
from byoda.datastore.document_store import DocumentStoreType

from byoda.requestauth.jwt import JWT

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.data_wsapi_client import DataWsApiClient

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from byoda import config

from podserver.util import get_environment_vars

MAX_RECONNECT_DELAY: int = 300

LOGFILE: str = '/var/www/wwwroot/logs/discover.log'

_LOGGER: Logger | None = None


async def main(argv):
    data: dict[str, str] = get_environment_vars()

    debug = data.get('debug', False)
    if debug and str(debug).lower() in ('true', 'debug', '1'):
        config.debug = True
        # Make our files readable by everyone, so we can
        # use tools like call_data_api.py to debug the server
        os.umask(0o0000)
    else:
        os.umask(0x0077)

    program_name: str = os.path.basename(argv[0]).rstrip('.py')
    global _LOGGER
    _LOGGER = Logger.getLogger(
        program_name, json_out=True, debug=config.debug,
        loglevel=data.get('worker_loglevel', 'ERROR'), logfile=LOGFILE
    )

    # We start before the pod app server is up, so we need to wait a bit
    # as the pod app server creates the PubSub setup
    await sleep(30)

    _LOGGER.debug('Starting discover_worker')

    account = await setup_account(sys.argv)
    server: PodServer = config.server
    cache_store: CacheStore = server.cache_store
    data_store: DataStore = server.data_store

    await account.update_memberships(
        data_store, cache_store, with_pubsub=False
    )

    # TODO: pick up new membershisp without having to restart
    async with create_task_group() as tg:
        member: Member
        for member in account.memberships.values():

            # We use this JWT to call the Data API of our own pod to
            # store new data, which triggers PubSub messages to be sent
            member_jwt: JWT = JWT.create(
                member.member_id, IdType.MEMBER, member.data_secret,
                member.network.name, member.service_id, IdType.MEMBER,
                member.member_id
            )
            await setup_listener_for_membership(
                member, data_store, member_jwt, tg
            )


async def setup_listener_for_membership(member: Member, data_store: DataStore,
                                        member_jwt: JWT, tg: TaskGroup
                                        ) -> None:
    '''
    Sets up listening for updates for a membership of the local pod

    :param member: the membership of the service in the local pod
    :param data_store: the data store in the local pod get data of
    the network_links data class from
    :param member_jwt: the JWT to use for calling the Data API of our
    own pod to store new data
    :returns: (none)
    :raises: (none)
    '''
    # First we iniate listening to the network_links class of our
    # own membership on the local pod so that we can add new links
    # immediately when they are created
    await listen_local_network_links_table(member, member_jwt, tg)

    # Then we initiate listening to the remote pods that we
    # already have network links to
    service_id: int = member.service_id
    schema: Schema = member.schema
    listen_relations: list[ListenRelation] | None = schema.listen_relations
    if not listen_relations:
        _LOGGER.debug(f'No listen relations defined for service {service_id}')
        return

    network_links = await get_current_network_links(member, data_store)
    _LOGGER.debug(f'Found {len(network_links or [])} network links')

    connected_peers: dict[UUID, set[str]] = {}

    network_link: dict[str, object]
    for network_link in network_links:
        if 'member_id' not in network_link or 'relation' not in network_link:
            _LOGGER.debug(
                f'Invalid network link: {network_link}, skipping'
            )
            continue

        remote_member_id: UUID = network_link['member_id']
        relation: str = network_link['relation']

        listen_relation: ListenRelation
        for listen_relation in listen_relations:
            listen_class_name: str = listen_relation.class_name
            if relation not in listen_relation.relations:
                _LOGGER.debug(
                    f'Skipping relation {relation} to member '
                    f'{remote_member_id} as it is not in '
                    f'{listen_relation.relations} for '
                    f'class {listen_class_name}'
                )
                continue

            if remote_member_id not in connected_peers:
                connected_peers[remote_member_id]: set[str] = set()
            elif listen_class_name in connected_peers[remote_member_id]:
                # we are already connected to the peer
                continue

            connected_peers[remote_member_id].add(listen_class_name)

            dest_class_name: str = listen_relation.destination_class

            _LOGGER.debug(
                f'Initiating connection to {remote_member_id} '
                f'with relation {relation} for class {listen_class_name} '
                f'in service {service_id} to store '
                f'in class {dest_class_name}'
            )

            tg.start_soon(
                get_updates, remote_member_id, listen_class_name,
                dest_class_name, member, member_jwt
            )


async def listen_local_network_links_table(member: Member, member_jwt: JWT,
                                           tg: TaskGroup) -> None:
    '''
    Sets up the worker to listen for changes to the network_links for a
    membership of the pod.

    When we discover a new network link, we need to initiate a connection
    to the membership of the remote pod and listen to updates of the
    data classes specified as listen relations in the schema for the service.

    :param member: the membership of the service in the local pod
    :param member_jwt: the JWT to use for calling the Data API of our
    own pod to store new data
    :param tg: the task group to use for creating the new task
    :returns: None
    :raises: None
    '''

    schema: Schema = member.schema
    service_id: int = member.service_id

    # This gets us the process ID so we can start listening to the
    # local pubsub socket for updates to the 'network_links' data class
    process_id: int = find_process_id(PubSubNng.get_directory(service_id))

    listen_relations: list[ListenRelation] = schema.listen_relations

    # This listens to the events for network_links on the local pod
    # so that it can immediately start following a remote pod, without
    # #having to wait for the 'sleep()' command to complete, when
    # the member has added the network relation
    pubsub = PubSubNng(
        schema.data_classes[MARKER_NETWORK_LINKS], schema, False, False,
        process_id
    )

    for listen_relation in listen_relations:
        # TODO: for now relations must be the same for each listen_relation
        class_name: str = listen_relation.class_name
        relations: list[str] = listen_relation.relations
        dest_class_name: str = listen_relation.destination_class

        _LOGGER.info(
            f'Starting to listen for changes to class {MARKER_NETWORK_LINKS} '
            f'for new relations matching {", ".join(relations or ["(any)"])} '
            f'in service {service_id}'
        )
        tg.start_soon(
            get_network_link_updates, pubsub, class_name, dest_class_name,
            member, member_jwt, relations, tg
        )


async def get_network_link_updates(pubsub: PubSubNng, listen_class_name: str,
                                   dest_class_name: str, member: Member,
                                   member_jwt: JWT, relations: list[str],
                                   tg: TaskGroup) -> None:
    '''
    Locally monitors newly created network links to remote pods, initates
    listening to those remote pods and sends updates to other tasks about the
    new pod it has discovered

    :param pubsub: the pubsub object to use for listening to updates to
    the network links class in the local pod
    :param listen_class_name: the name of the data class to listen to updates
    :param dest_class_name: the class name to store the data in
    :param member: the membership of the service in the local pod
    :param member_jwt: the JWT to use for calling the Data API of our
    own pod to store new data
    :param relations: the relations with pods that we want to listen to
    :param tg: the task group that tasks for newly added remote pods should
    be created under
    '''

    # TODO: we also need logic to handle updated and deleted network links
    connected_targets: set[UUID] = set()
    while True:
        try:
            messages: list[PubSubMessage] = await pubsub.recv()
            message: PubSubMessage
            for message in messages:
                result = review_message(
                    message, listen_class_name, relations, connected_targets
                )
                if not result:
                    continue

                _LOGGER.debug(
                    f'Initiating connection to pod of '
                    f'member {message.remote_member_id}'
                )

                remote_member_id: UUID = message.data['remote_member_id']
                tg.start_soon(
                    get_updates, remote_member_id, listen_class_name,
                    dest_class_name, member, member_jwt
                )
                connected_targets.add(remote_member_id)
        except Exception as exc:
            _LOGGER.exception(
                f'Update failure for append to {message.class_name}: {exc}'
            )


def review_message(message: PubSubMessage, listen_class_name: str,
                   relations: list[str], connected_targets: set[UUID]) -> bool:
    '''
    Reviews the received message, returns True if the message should be
    processed, False otherwise

    :param message: the message to review
    :returns: whether the message should be processed
    :raises:
    '''

    if message.action != PubSubMessageAction.APPEND:
        _LOGGER.warning(
            f'Ignoring action {message.action.value} '
            f'for {listen_class_name}'
        )
        return False

    data: dict[str, object] = message.data
    _LOGGER.debug(f'Received data {data}')
    remote_member_id = data['member_id']
    relation: str = data['relation']
    _LOGGER.debug(
        f'Received update for class {message.class_name}, '
        f'action: {message.action.value} for relation {relation} '
        f'with member {remote_member_id}'
    )

    if relations and relation not in relations:
        _LOGGER.debug(
            f'Relation {relation} not in {relations}, '
            f'not creating listener for member {remote_member_id}'
        )
        return False

    if remote_member_id in connected_targets:
        _LOGGER.debug(
            f'Already connected to pod of member {remote_member_id}'
        )
        return False

    return True


async def get_updates(remote_member_id: UUID, listen_class_name: str,
                      dest_class_name: str, member: Member, member_jwt: JWT
                      ) -> None:
    '''
    Listen to updates for a class from a remote pod and inject the updates
    into to the specified class in the local pod

    :param remote_member_id: the member ID of the remote pod to listen to
    :param class_name: the name of the data class to listen to updates for
    :param network_name: the name of the network that the pod is in
    :param member: the membership of the service in the local pod
    :param target_table: the table in the local pod where to store data
    :returns: (none)
    :raises: (none))
    '''

    service_id: int = member.service_id
    _LOGGER.debug(
        f'Connecting to remote member {remote_member_id} for updates '
        f'to class {listen_class_name} of service {member.service_id}'
    )

    # Aggressive retry as we're talking to our own pod
    reconnect_delay: int = 0.2
    while True:
        try:
            async for result in DataWsApiClient.call(
                    service_id, listen_class_name, DataRequestType.UPDATES,
                    member.tls_secret, member_id=remote_member_id,
                    network=member.network.name
            ):
                edge_data: dict = orjson.loads(result)
                remote_member: UUID = UUID(edge_data['origin_id'])
                data: dict[str, object] = edge_data['node']
                _LOGGER.debug(
                    f'Appending data from class {listen_class_name} '
                    f'originating from {remote_member} '
                    f'received from member {remote_member_id}'
                    f'to class {dest_class_name}: {data}'
                )

                # We call the Data API against the internal endpoint
                # (http://127.0.0.1:8000) to ingest the data into the local
                # pod asthat will trigger the /updates WebSocket API to send
                # the notifications
                query_id: UUID = uuid4()
                resp: HttpResponse = await DataApiClient.call(
                    member.service_id, dest_class_name, DataRequestType.APPEND,
                    member_id=member.member_id, data={'data': data},
                    headers=member_jwt.as_header(),
                    query_id=query_id, internal=True
                )
                if resp.status_code != 200:
                    _LOGGER.warning(
                        f'Failed to append video {data.get("asset_id")} '
                        f'to class {dest_class_name} '
                        f'with query_id {query_id}: {resp.status_code}'
                    )
                    return None
                _LOGGER.debug(
                    f'Successfully appended data: {resp.status_code}'
                )
                reconnect_delay = 1
        except (ConnectionClosedOK, ConnectionClosedError, WebSocketException,
                ConnectionRefusedError) as exc:
            _LOGGER.exception(
                f'Websocket client transport error to {member.member_id}. '
                f'Will reconnect in {reconnect_delay} secs: {exc}'
            )
        except socket_gaierror as exc:
            _LOGGER.exception(
                f'Websocket connection to member {member.member} failed: {exc}'
            )
        except CancelledError as exc:
            _LOGGER.exception(
                f'Websocket connection to member {member.member} cancelled by '
                f'asyncio: {exc}'
            )
        except Exception as exc:
            _LOGGER.exception(
                f'Failed to establish connection to the membership '
                f'of our pod: {exc}'
            )

        await sleep(reconnect_delay)

        reconnect_delay += 2 * random() * reconnect_delay
        if reconnect_delay > MAX_RECONNECT_DELAY:
            reconnect_delay = MAX_RECONNECT_DELAY


def find_process_id(pubsub_dir: str = PubSubNng.PUBSUB_DIR) -> int:
    '''
    Finds the process ID of the process that is sending to the Nng socket
    '''

    process_id = None
    for file in os.listdir(pubsub_dir):
        if file.startswith('network_links.pipe'):
            process_id = file.split('-')[-1]
            _LOGGER.debug(f'Found app server process ID {process_id}')
            return int(process_id)

    raise RuntimeError(f'Could not find process ID from: {pubsub_dir}')


async def get_current_network_links(member: Member, data_store: DataStore
                                    ) -> list[ResultData]:
    '''
    Gets the current network links of the local pod to create the initial
    set of remote pods to listen to

    :param member: the membership of the service in the local pod
    :returns: a list of network links
    '''

    schema: Schema = member.schema
    data_class: SchemaDataArray = schema.data_classes[MARKER_NETWORK_LINKS]

    _LOGGER.debug(
        f'Getting existing network links for {member.member_id} '
        f'from class {data_class.name} tom store type {type(data_store)}'
    )

    data: list[QueryResult] = await data_store.query(
        member_id=member.member_id, data_class=data_class, filters={}
    )
    _LOGGER.debug(f'Found {len(data or [])} existing network links')

    network_links: list[ResultData] = [
        edge_data for edge_data, _ in data or []
    ]

    return network_links


async def setup_account(argv):
    data: dict[str, str] = get_environment_vars()

    debug = data.get('debug', False)
    if debug and str(debug).lower() in ('true', 'debug', '1'):
        config.debug = True
        # Make our files readable by everyone, so we can
        # use tools like call_data_api.py to debug the server
        os.umask(0o0000)
    else:
        os.umask(0x0077)

    _LOGGER.debug(
        f'Starting discover_worker {data["bootstrap"]}: '
        f'daemonize: {data["daemonize"]}'
    )

    try:
        server: PodServer = PodServer(
            cloud_type=CloudType(data['cloud']),
            bootstrapping=bool(data.get('bootstrap'))
        )
        config.server = server

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE, server.cloud,
            private_bucket=data['private_bucket'],
            restricted_bucket=data['restricted_bucket'],
            public_bucket=data['public_bucket'],
            root_dir=data['root_dir']
        )

        network: Network = Network(data, data)
        await network.load_network_secrets()

        server.network = network
        server.paths = network.paths

        account = Account(data['account_id'], network)
        await account.paths.create_account_directory()
        await account.load_secrets()

        server.account = account

        await server.set_data_store(
            DataStoreType.SQLITE, account.data_secret
        )
        await server.set_cache_store(CacheStoreType.SQLITE)

    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

    return account


if __name__ == '__main__':
    run(
        main, sys.argv,
        backend='asyncio',
        backend_options={'use_uvloop': True}
    )
