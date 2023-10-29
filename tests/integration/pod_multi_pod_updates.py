#!/usr/bin/env python3

'''
Test receiving websocket updates from multiple pods

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license
'''

import os
import sys
import shutil
import unittest

from uuid import UUID
from random import random
from datetime import datetime
from datetime import timezone

import orjson

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
from byoda.datamodel.table import Table
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.table import ResultData

from byoda.datatypes import DataRequestType
from byoda.datatypes import MARKER_NETWORK_LINKS
from byoda.datatypes import IdType
from byoda.datamodel.table import QueryResult

from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.storage.pubsub_nng import PubSubNng
from byoda.datastore.data_store import DataStore
from byoda.datastore.cache_store import CacheStore

from byoda.servers.pod_server import PodServer

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.data_wsapi_client import DataWsApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger

from byoda import config

from tests.lib.setup import mock_environment_vars
from tests.lib.setup import setup_network
from tests.lib.setup import setup_account
from tests.lib.setup import get_account_id
from tests.lib.setup import get_test_uuid

from tests.lib.defines import AZURE_POD_ACCOUNT_ID
from tests.lib.defines import AZURE_POD_MEMBER_ID
from tests.lib.defines import AWS_POD_MEMBER_ID
from tests.lib.defines import GCP_POD_MEMBER_ID
from tests.lib.defines import HOME_POD_MEMBER_ID
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

from tests.lib.util import get_member_tls_headers

# Settings must match config.yml used by directory server
NETWORK = config.DEFAULT_NETWORK
SLEEP_INTERVAL: int = 60
TIMEOUT: int = 900
MAX_RECONNECT_DELAY: int = 300
MAX_SUBSCRIBES = 1000

TEST_DIR: str = '/tmp/byoda-tests/podserver'

_LOGGER = None

TARGET_MEMBERS = [
    AZURE_POD_MEMBER_ID, AWS_POD_MEMBER_ID, GCP_POD_MEMBER_ID,
    HOME_POD_MEMBER_ID
]

CONNECTED_TARGETS: dict[int, set] = dict()

LISTEN_RESULT: bool = False


async def prep_tests(work_dir: str = TEST_DIR
                     ) -> tuple[Account, Member, str, str]:
    shutil.copy(
        'tests/collateral/addressbook.json', f'{work_dir}/addressbook.json'
    )
    mock_environment_vars(work_dir)
    network_data = await setup_network(delete_tmp_dir=False)

    network_data['account_id'] = get_account_id(network_data)
    account = await setup_account(network_data, clean_pubsub=False)
    server: PodServer = config.server

    member = await account.get_membership(ADDRESSBOOK_SERVICE_ID)
    schema: Schema = member.schema

    data_store: DataStore = config.server.data_store
    await data_store.setup_member_db(
            member.member_id, member.service_id, schema
    )

    server.data_store: DataStore = data_store

    azure_member = await azure_account_setup(member.service_id, work_dir)

    return (account, azure_member)


async def azure_account_setup(service_id: int = ADDRESSBOOK_SERVICE_ID,
                              work_dir: str = TEST_DIR) -> Member:
    files = (
        'azure-pod-member-cert.pem', 'azure-pod-member.key',
        'azure-pod-member-data-cert.pem', 'azure-pod-member-data.key',
        'azure-pod-private-key-password'
    )
    local_collateral_dir = 'tests/collateral/local'
    for file in files:
        shutil.copy(f'{local_collateral_dir}/{file}', f'{work_dir}/{file}')

    server: PodServer = config.server

    azure_account = Account(AZURE_POD_ACCOUNT_ID, network=server.network)
    azure_member = Member(service_id, azure_account)
    azure_member.member_id = AZURE_POD_MEMBER_ID

    tls_secret = MemberSecret(
        azure_member.member_id, azure_member.service_id, account=azure_account
    )

    tls_secret.cert_file = 'azure-pod-member-cert.pem'
    tls_secret.private_key_file = 'azure-pod-member.key'
    with open(f'{work_dir}/azure-pod-private-key-password') as file_desc:
        private_key_password = file_desc.read().strip()

    await tls_secret.load(
        with_private_key=True, password=private_key_password
    )

    data_secret = MemberDataSecret(
        azure_member.member_id, azure_member.service_id
    )

    data_secret.cert_file = 'azure-pod-member-data-cert.pem'
    data_secret.private_key_file = 'azure-pod-member-data.key'

    await data_secret.load(
        with_private_key=True, password=private_key_password
    )

    tls_secret.save_tmp_private_key()

    azure_member.tls_secret: MemberSecret = tls_secret
    azure_member.data_secret: MemberDataSecret = data_secret

    return azure_member


async def add_network_link(member: Member, remote_member_id: UUID,
                           relation: str) -> int:
    '''
    Adds a relation to the network_links data class

    :param member_id: member_id for who to update the network_links data class
    :param remote_member_id: member_id of the remote member to be added
    :param relation: relation to be added

    :returns: the number of records added to the data class
    '''

    service_id: int = member.service_id
    class_name: str = 'network_links'
    action: DataRequestType = DataRequestType.APPEND

    auth_headers = get_member_tls_headers(
        member.member_id, member.network.name, service_id
    )
    data = {
        'data': {
            'created_timestamp': datetime.now(tz=timezone.utc),
            'member_id': remote_member_id,
            'relation': relation
        }
    }

    resp: HttpResponse = await DataApiClient.call(
        service_id, class_name, action, headers=auth_headers, data=data,
        member_id=member.member_id, internal=True
    )
    _LOGGER.debug(f'Data API append result: {resp.status_code}')

    return resp.status_code


async def add_azure_asset(azure_member: Member, service_id: int,
                          network_name: str):
    class_name: str = 'public_assets'
    action: DataRequestType = DataRequestType.APPEND

    data: dict[str, str | UUID | datetime] = {
        'data': {
            'created_timestamp': datetime.now(tz=timezone.utc),
            'asset_id': get_test_uuid(),
            'asset_type': 'video',
        }
    }
    resp: HttpResponse = await DataApiClient.call(
        service_id, class_name, action, secret=azure_member.tls_secret,
        data=data, member_id=azure_member.member_id, network=network_name
    )
    _LOGGER.debug(f'Azure member Data API append result: {resp.status_code}')


def find_process_id(pubsub_dir: str = PubSubNng.PUBSUB_DIR) -> int:
    '''
    Finds the process ID of the process that is sending to the Nng socket
    '''

    process_id = None
    for file in os.listdir(pubsub_dir):
        if file.startswith('network_links.pipe'):
            process_id = file.split('-')[-1]
            return int(process_id)

    raise RuntimeError(f'Could not find process ID from: {pubsub_dir}')


async def listen_local_network_links_table(member: Member,
                                           cache_store: CacheStore,
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

        _LOGGER.debug(f'Getting caching table for class {destination_class}')

        target_table: Table = cache_store.backend.get_table(
            member.member_id, destination_class
        )

        _LOGGER.info(
            f'Starting to listen for changes to class {MARKER_NETWORK_LINKS} '
            f'for new relations matching {", ".join(relations or ["(any)"])} '
            f'in service {service_id}'
        )
        tg.start_soon(
            get_network_link_updates, pubsub, class_name, member.service_id,
            network.name, member, target_table, relations, tg
        )


async def get_network_links(member: Member) -> list[dict[str, object]]:
    server: PodServer = config.server
    data_store: DataStore = server.data_store
    schema: Schema = member.schema
    data_class: SchemaDataArray = schema.data_classes[MARKER_NETWORK_LINKS]

    data: list[QueryResult] = await data_store.query(
        member_id=member.member_id, data_class=data_class, filters={}
    )
    _LOGGER.debug(f'Found {len(data or [])} network links')

    return data or []


async def get_network_link_updates(pubsub: PubSubNng, class_name: str,
                                   service_id: int, network_name: str,
                                   member: Member,
                                   target_table: Table,
                                   relations: list[str], tg):
    while True:
        raw_data = await pubsub.subs[0].arecv()
        try:
            meta = orjson.loads(raw_data)
            data = meta['data']
            member_id = UUID(data['member_id'])
            _LOGGER.debug(
                f'Received updata for class {meta["class_name"]}, '
                f'action: {meta["action"]} for relation {data["relation"]} '
                f'with member {member_id}'
            )
            if data['relation'] in relations:
                global CONNECTED_TARGETS
                if member_id not in CONNECTED_TARGETS[service_id]:
                    CONNECTED_TARGETS[service_id].add(member_id)
                    tg.start_soon(
                        get_updates, class_name, service_id,
                        network_name, member, target_table
                    )
        except Exception as exc:
            _LOGGER.debug(
                f'Update failure: {exc} for data {raw_data.decode("utf-8")}'
            )


async def get_updates(remote_member_id: UUID, class_name: str, service_id: int,
                      network_name: str, member: Member,
                      target_table: Table):

    _LOGGER.debug(f'Connecting to remote member {remote_member_id}')
    reconnect_delay = 1
    while True:
        try:
            async for result in DataWsApiClient.call(
                service_id, class_name, DataRequestType.UPDATES,
                member.tls_secret, member_id=remote_member_id,
                network=network_name
            ):
                edge_data: dict = orjson.loads(result)
                _LOGGER.debug(f'Received: {edge_data}')
                remote_member: UUID = UUID(edge_data['origin'])
                data: dict[str, object] = edge_data['node']
                cursor: str = target_table.get_cursor_hash(data, remote_member)
                await target_table.append(
                    data, cursor, remote_member_id, IdType.MEMBER, class_name
                )
                global LISTEN_RESULT
                LISTEN_RESULT = True
            reconnect_delay = 1
        except (ConnectionClosedError, WebSocketException) as exc:
            _LOGGER.debug(
                f'Websocket client transport error: {exc}'
            )
            await sleep(reconnect_delay)

            reconnect_delay += 2 * random() * reconnect_delay
            if reconnect_delay > MAX_RECONNECT_DELAY:
                reconnect_delay = MAX_RECONNECT_DELAY


class TestMultiPodUpdates(unittest.IsolatedAsyncioTestCase):
    async def test_multi_pod_listen(self):
        account, azure_member = await prep_tests()

        data_store: DataStore = config.server.data_store
        cache_store: CacheStore = config.server.cache_store
        network: Network = account.network

        await account.update_memberships(
            data_store, cache_store, with_pubsub=False
        )

        async with create_task_group() as tg:
            member: Member
            for member in account.memberships.values():
                await data_store.setup_member_db(
                    member.member_id, member.service_id, member.schema
                )

                await cache_store.setup_member_db(
                    member.member_id, member.service_id, member.schema
                )

                await setup_listener_for_membership(
                    self, account, member, azure_member, network.name,
                    cache_store, data_store, tg
                )


async def setup_listener_for_membership(test, account: Account,
                                        member: Member, azure_member: Member,
                                        network_name: str,
                                        cache_store: CacheStore,
                                        data_store: DataStore, tg: TaskGroup
                                        ) -> None:
    '''
    Sets up listening for updates for a membership of the local pod

    :param member: the membership of the service in the local pod

    '''
    # First we iniate listening to the network_links class of our
    # own membership on the local pod
    await listen_local_network_links_table(member, cache_store, tg)

    connected_peers: set[UUID] = set()
    asset_added: bool = False
    while not asset_added:
        service_id: int = member.service_id
        schema: Schema = member.schema

        discovered_links: list[QueryResult] = await get_network_links(
            member
        )
        discovered_targets: set[UUID] = set(
            link[0]['member_id'] for link in discovered_links or []

        )
        new_targets: set[UUID] = \
            discovered_targets - connected_peers

        total_target_count = len(connected_peers) + len(new_targets)
        if total_target_count > MAX_SUBSCRIBES:
            additional_targets = \
                MAX_SUBSCRIBES - len(connected_peers)
            new_targets = \
                set(list(new_targets)[0:additional_targets])

        for remote_member_id in new_targets:
            for listen in schema.listen_relations:
                class_name: str = listen.class_name

                target_table: Table = cache_store.backend.get_table(
                    member.member_id, listen.destination_class
                )

                _LOGGER.debug(
                    f'Initiating connection to {remote_member_id} '
                    f'for service {service_id} '
                    f'for class {class_name}'
                )
                tg.start_soon(
                    get_updates, remote_member_id, class_name,
                    service_id, network_name, member, target_table
                )
                connected_peers.add(remote_member_id)

        await sleep(1)
        if len(discovered_links) < len(TARGET_MEMBERS):
            targets: UUID = TARGET_MEMBERS[len(discovered_links)]
            await add_network_link(
                member=member,
                remote_member_id=targets,
                relation='follow'
            )
        elif (len(discovered_links) == len(TARGET_MEMBERS)
                and not asset_added):
            await add_azure_asset(
                azure_member, service_id, network_name
            )
            asset_added = True

    # Wait for the update from the Azure pod to come in
    await sleep(10)

    tg.cancel_scope.cancel()
    test.assertTrue(asset_added)
    test.assertTrue(LISTEN_RESULT)


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

if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    # run(main, backend='asyncio', backend_options={'use_uvloop': True})
    unittest.main()
