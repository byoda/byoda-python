#!/usr/bin/env python3

'''
Test receiving websocket updates from multiple pods

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license
'''

import sys
import shutil
import unittest

from uuid import UUID
from logging import Logger
from datetime import datetime
from datetime import timezone

from anyio import sleep
from anyio import create_task_group
from anyio.abc import TaskGroup

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.dataclass import SchemaDataArray

from byoda.datatypes import DataRequestType
from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.datamodel.table import QueryResult

from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.datastore.data_store import DataStore
from byoda.datastore.cache_store import CacheStore

from byoda.servers.pod_server import PodServer

from byoda.util.updates_listener import UpdateListenerMember

from byoda.util.api_client.data_api_client import DataApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from podserver.podworker.discovery import listen_local_network_links_tables
from podserver.podworker.discovery import get_current_network_links

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
    Adds a relation to the network_links data class of the locally running pod

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
        member_id=member.member_id, internal=True, timeout=300
    )
    _LOGGER.debug(f'Data API append result: {resp.status_code}')

    return resp.status_code


async def add_azure_asset(azure_member: Member, service_id: int,
                          network_name: str) -> None:
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


class TestMultiPodUpdates(unittest.IsolatedAsyncioTestCase):
    async def test_multi_pod_listen(self):
        account, azure_member = await prep_tests()
        service_id: int = ADDRESSBOOK_SERVICE_ID
        data_store: DataStore = config.server.data_store
        cache_store: CacheStore = config.server.cache_store

        await account.update_memberships(
            data_store, cache_store, with_pubsub=False
        )

        member = await account.get_membership(service_id)

        # Add an initial network link so we can test processing
        # existing network links
        await add_network_link(member, GCP_POD_MEMBER_ID, 'follow')

        listeners: dict[UUID, UpdateListenerMember] = \
            await get_current_network_links(account, data_store)

        # First we iniate listening to the network_links class of our
        # own membership on the local pod
        task_group: TaskGroup
        async with create_task_group() as task_group:
            await listen_local_network_links_tables(
                account, listeners, task_group
            )

            listener: UpdateListenerMember
            for listener in listeners.values():
                await listener.get_all_data()
                task_group.start_soon(listener.get_updates)

            await setup_listener_for_membership(
                self, member, azure_member, account.network.name,
                listeners, task_group
            )


async def setup_listener_for_membership(
        test, member: Member, azure_member: Member,
        network_name: str, listeners: dict[UUID, UpdateListenerMember],
        task_group: TaskGroup) -> None:
    '''
    Sets up listening for updates for a membership of the local pod

    :param member: the membership of the service in the local pod

    '''

    link_added: bool = False
    asset_added: bool = False
    service_id: int = member.service_id

    while not asset_added:
        if not link_added:
            await add_network_link(
                member=member,
                remote_member_id=AZURE_POD_MEMBER_ID,
                relation='follow'
            )
            link_added = True
        elif AZURE_POD_MEMBER_ID in listeners and not asset_added:
            await add_azure_asset(
                azure_member, service_id, network_name
            )
            asset_added = True

        await sleep(1)

    # Wait for the update from the Azure pod to come in
    await sleep(10)

    task_group.cancel_scope.cancel()
    test.assertTrue(asset_added)


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)
    unittest.main()
