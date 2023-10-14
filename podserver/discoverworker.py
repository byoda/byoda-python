#!/usr/bin/env python3

'''
Test receiving websocket updates from multiple pods

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import sys

from uuid import UUID
from random import random
from datetime import datetime

import orjson

from anyio import run
from anyio import sleep
from anyio import create_task_group
from anyio.abc import TaskGroup

from websockets.exceptions import ConnectionClosedError
from websockets.exceptions import WebSocketException

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.schema import ListenRelation
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.table import Table
from byoda.datamodel.table import ResultData
from byoda.datamodel.table import QueryResults

from byoda.datatypes import MemberStatus
from byoda.datatypes import DataRequestType
from byoda.datatypes import CloudType
from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.storage.pubsub_nng import PubSubNng
from byoda.datastore.data_store import DataStore
from byoda.datastore.data_store import DataStoreType

from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.data_wsapi_client import DataWsApiClient

from byoda.util.logger import Logger

from byoda import config

from podserver.util import get_environment_vars

MAX_RECONNECT_DELAY: int = 300

LOGFILE: str = '/var/www/wwwroot/logs/discover.log'

_LOGGER: Logger | None = None


async def main():
    account = await setup_account(sys.argv)
    network: Network = account.network
    server: PodServer = config.server
    data_store: DataStore = server.data_store

    _LOGGER.debug('Discover worker starting up')

    memberships: set[int, Member] = await get_current_memberships(
        account
    )

    _LOGGER.debug(f'Found {len(memberships or [])} existing memberships')

    # TODO: we need to avoid creating duplicate listeners for the same
    # class & pod, which can happen when we have multiple network links
    # to the remote pod
    async with create_task_group() as tg:
        member: Member
        for member in memberships.values():
            schema: Schema = member.schema
            schema.get_data_classes()
            await data_store.setup_member_db(
                member.member_id, member.service_id, member.schema
            )

            await setup_listener_for_membership(
                member, network.name, data_store, tg
            )


async def setup_listener_for_membership(member: Member, network_name: str,
                                        data_store: DataStore, tg: TaskGroup
                                        ) -> None:
    '''
    Sets up listening for updates for a membership of the local pod

    :param member: the membership of the service in the local pod

    '''
    # First we iniate listening to the network_links class of our
    # own membership on the local pod so that we can add new links
    # immediately when they are created
    await listen_local_network_links_table(member, data_store, tg)

    # Then we initiate listening to the remote pods that we
    # already have network links to
    service_id: int = member.service_id
    schema: Schema = member.schema
    listen_relations: list[ListenRelation] = schema.listen_relations

    network_links = await get_current_network_links(member)
    _LOGGER.debug(f'Found {len(network_links or [])} network links')

    connected_peers: dict[UUID, set[str]] = {}

    network_link: dict[str, object]
    for network_link in network_links:
        remote_member_id: UUID = network_link['member_id']
        relation: str = network_link['relation']

        listen_relation: ListenRelation
        for listen_relation in listen_relations:
            class_name: str = listen_relation.class_name
            if relation not in listen_relation.relations:
                _LOGGER.debug(
                    f'Relation {relation} to member {remote_member_id} '
                    f'not in {listen_relation.relations} '
                    f'for class {class_name}'
                )
                continue

            if remote_member_id not in connected_peers:
                connected_peers[remote_member_id]: set[str] = set()
            elif class_name in connected_peers[remote_member_id]:
                # we are already connected to the peer
                continue

            connected_peers[remote_member_id].add(class_name)

            destination_class: str = listen_relation.destination_class
            target_table: Table = data_store.backend.get_table(
                member.member_id, destination_class
            )

            _LOGGER.debug(
                f'Initiating connection to {remote_member_id} '
                f'with relation {relation} for class {class_name} '
                f'in service {service_id} to store '
                f'in class {destination_class}'
            )

            tg.start_soon(
                get_updates, remote_member_id, class_name,
                network_name, member, target_table
            )


async def listen_local_network_links_table(member: Member,
                                           data_store: DataStore,
                                           tg: TaskGroup) -> None:
    '''
    Sets up the worker to listen for changes to the network_links for a
    membership of the pod.

    When we discover a new network link, we need to initiate a connection
    to the membership of the remote pod and listen to updates of the
    data classes specified as listen relations in the schema for the service.

    :param member: the membership of the service in the local pod
    :param data_store: the data store in the local pod where to store
    data retrieved for the data class from the membership of the remote pod
    :param tg: the task group to use for creating the new task
    :returns: None
    :raises: None
    '''

    schema: Schema = member.schema
    service_id: int = member.service_id
    network: Network = member.network

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
        destination_class: str = listen_relation.destination_class

        target_table: Table = data_store.backend.get_table(
            member.member_id, destination_class
        )

        _LOGGER.debug(
            f'Starting to listen for changes to class {MARKER_NETWORK_LINKS} '
            f'for new relations matching {", ".join(relations or ["(any)"])} '
            f'in service {service_id}'
        )
        tg.start_soon(
            get_network_link_updates, pubsub, class_name, network.name,
            member, target_table, relations, tg
        )


async def get_network_link_updates(pubsub: PubSubNng, class_name: str,
                                   network_name: str, member: Member,
                                   target_table: Table, relations: list[str],
                                   tg: TaskGroup) -> None:
    '''
    Locally monitors newly created network links to remote pods, initates
    listening to those remote pods and sends updates to other tasks about the
    new pod it has discovered

    :param pubsub: the pubsub object to use for listening to updates to
    the updates to network links in the local pod
    :param class_name: the name of the data class to listen to updates for
    :param service_id: the service ID of the membership
    :param network_name: the name of the network that the pod is in
    :param member: the membership of the service in the local pod
    :param target_table: the table in the local pod where to store data
    from pods that we listen to
    :param relations: the relations with pods that we want to listen to
    :param tg: the task group that tasks for newly added remote pods should
    be created under
    :param sendstreams: the message stream to send messages about newly
    linked pods to other tasks
    '''

    # TODO: we also need logic to handle updated and deleted network links
    connected_targets: set[UUID] = set()
    while True:
        raw_data = await pubsub.subs[0].arecv()
        try:
            meta = orjson.loads(raw_data)
            if meta['action'] != 'append':
                _LOGGER.warning(
                    f'Ignoring action {meta["action"]} for {class_name}'
                )
                continue

            _LOGGER.debug(f'Received data {meta}')
            data = meta['data']
            remote_member_id = data['member_id']
            relation: str = data['relation']
            _LOGGER.debug(
                f'Received update for class {meta["class_name"]}, '
                f'action: {meta["action"]} for relation {data["relation"]} '
                f'with member {remote_member_id}'
            )
            if relations and relation not in relations:
                _LOGGER.debug(
                    f'Relation {relation} not in {relations}, '
                    f'not creating listener'
                )
                continue

            if remote_member_id in connected_targets:
                _LOGGER.debug(
                    f'Already connected to pod of member {remote_member_id}'
                )
                continue

            _LOGGER.debug(
                f'Initiating connection to pod of member {remote_member_id}'
            )

            tg.start_soon(
                get_updates, remote_member_id, class_name,
                network_name, member, target_table
            )
            connected_targets.add(remote_member_id)
        except Exception as exc:
            _LOGGER.exception(
                f'Update failure: {exc} for data {raw_data.decode("utf-8")}'
            )


async def get_updates(remote_member_id: UUID, class_name: str,
                      network_name: str, member: Member,
                      target_table: Table) -> None:
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
        f'to class {class_name} of service {member.service_id}'
    )

    reconnect_delay: int = 1
    while True:
        try:
            async for result in DataWsApiClient.call(
                    service_id, class_name, DataRequestType.UPDATES,
                    member.tls_secret, member_id=remote_member_id,
                    network=network_name
            ):
                edge_data: dict = orjson.loads(result)
                remote_member: UUID = UUID(edge_data['origin'])
                data: dict[str, object] = edge_data['node']
                cursor: str = target_table.get_cursor_hash(data, remote_member)
                table_name: str = target_table.table_name
                _LOGGER.debug(
                    f'Appending data for class {class_name} '
                    f'originating from {remote_member} '
                    f'received from member {remote_member_id}'
                    f'to table {table_name}: {data}'
                )
                await target_table.append(data, cursor)

                reconnect_delay = 1
        except (ConnectionClosedError, WebSocketException) as exc:
            _LOGGER.debug(
                f'Websocket client transport error to {remote_member_id}. '
                f'Will reconnect in {reconnect_delay} secs: {exc}'
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


async def get_current_memberships(account: Account) -> set[int, Member]:
    '''
    Gets the current memberships of the local pod

    :param account: the account of the local pod
    :returns: a set of memberships
    '''

    memberships: dict[UUID, dict[str, UUID | datetime | str]] = \
        await account.get_memberships(status=MemberStatus.ACTIVE)

    members: dict[int, Member] = {}
    for member_info in memberships.values():
        service_id: int = member_info['service_id']
        member: Member = await account.get_membership(service_id)
        members[service_id] = member

    _LOGGER.debug(f'Found {len(members or [])} memberships')

    return members


async def get_current_network_links(member: Member) -> list[ResultData]:
    '''
    Gets the current network links of the local pod to create the initial
    set of remote pods to listen to

    :param member: the membership of the service in the local pod
    :returns: a list of network links
    '''

    server: PodServer = config.server
    data_store: DataStore = server.data_store
    schema: Schema = member.schema
    data_class: SchemaDataArray = schema.data_classes[MARKER_NETWORK_LINKS]

    data: QueryResults = await data_store.query(
        member_id=member.member_id, data_class=data_class, filters={}
    )
    _LOGGER.debug(f'Found {len(data or [])} existing network links')

    network_links: list[ResultData] = [
        edge_data.data for edge_data, _ in data.items() or {}
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

    program_name: str = os.path.basename(argv[0]).rstrip('.py')
    global _LOGGER
    _LOGGER = Logger.getLogger(
        program_name, json_out=True, debug=config.debug,
        loglevel=data.get('worker_loglevel', 'WARNING'), logfile=LOGFILE
    )
    _LOGGER.debug(
        f'Starting podworker {data["bootstrap"]}: '
        f'daemonize: {data["daemonize"]}'
    )

    try:
        config.server: PodServer = PodServer(
            cloud_type=CloudType(data['cloud']),
            bootstrapping=bool(data.get('bootstrap'))
        )
        server: PodServer = config.server

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
    except Exception:
        _LOGGER.exception('Exception during startup')
        raise

    return account


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    run(
        main,
        backend='asyncio',
        backend_options={'use_uvloop': True}
    )
