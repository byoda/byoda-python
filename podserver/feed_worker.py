#!/usr/bin/env python3

'''
Listen for updates of pods in the network and store them in the local pod

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023, 2024, 2025
:license
'''

import os
import sys

from uuid import UUID
from datetime import UTC
from datetime import datetime
from logging import Logger

from anyio import run
from anyio import create_task_group
from anyio import sleep

from byoda.datamodel.network import Network
from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.memberdata import MemberData
from byoda.datamodel.schema import Schema
from byoda.datamodel.schema import ListenRelation
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.dataclass import SchemaDataObject
from byoda.datamodel.datafilter import DataFilterSet

from byoda.datamodel.pubsub_message import PubSubMessage

from byoda.datatypes import CloudType
from byoda.datatypes import NetworkLink
from byoda.datatypes import PubSubMessageAction

from byoda.storage.pubsub_nng import PubSubNng

from byoda.datastore.data_store import DataStore
from byoda.datastore.data_store import DataStoreType
from byoda.datastore.cache_store import CacheStore
from byoda.datastore.cache_store import CacheStoreType
from byoda.datastore.document_store import DocumentStoreType

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger as ByodaLogger

from byoda import config

from podserver.util import get_environment_vars

MAX_RECONNECT_DELAY: int = 300

LOGFILE: str = os.environ.get('LOGDIR', '/var/log/byoda') + '/feed.log'

_LOGGER: Logger | None = None


async def main(argv) -> None:
    # Before we do anything, we first wait for the podserver
    # to startup and do what it needs to do
    await sleep(60)

    data: dict[str, str] = get_environment_vars()

    debug: str | bool = data.get('debug', False)
    if debug and str(debug).lower() in ('true', 'debug', '1'):
        config.debug = True
        # Make our files readable by everyone, so we can
        # use tools like call_data_api.py to debug the server
        os.umask(0o0000)
    else:
        os.umask(0x0077)

    program_name: str = os.path.basename(argv[0]).rstrip('.py')
    global _LOGGER
    _LOGGER: Logger = ByodaLogger.getLogger(
        program_name, json_out=True, debug=config.debug,
        loglevel=data.get('worker_loglevel', 'ERROR'), logfile=LOGFILE
    )

    # We start before the pod app server is up, so we need to wait a bit
    # as the pod app server creates the PubSub setup
    _LOGGER.debug('Sleeping for 30 seconds')
    await sleep(30)

    account: Account = await setup_account(sys.argv)
    server: PodServer = config.server

    server.cdn_fqdn = data.get('cdn_fqdn')
    server.cdn_origin_site_id = data.get('cdn_origin_site_id')

    cache_store: CacheStore = server.cache_store
    data_store: DataStore = server.data_store

    _LOGGER.debug('Feed worker starting up')

    await account.update_memberships(
        data_store, cache_store, with_pubsub=False
    )

    # TODO: we need to avoid creating duplicate listeners for the same
    # class & pod, which can happen when we have multiple network links
    # to the remote pod
    async with create_task_group() as tg:
        member: Member
        for member in account.memberships.values():
            # First we iniate listening to the network_links class of our
            # own membership on the local pod so that we can add new links
            # immediately when they are created
            listen_relation: ListenRelation
            for listen_relation in member.schema.listen_relations:
                _LOGGER.debug(
                    f'Initating task for service {member.service_id} '
                    f'for dest class {listen_relation.feed_class}'
                )
                tg.start_soon(setup_listen, server, member, listen_relation)


async def setup_listen(server: PodServer, member: Member,
                       listen_relation: ListenRelation) -> None:
    '''
    Sets up the worker to listen for changes to the 'destination_class'
    specified by one of the 'listen_relations' specified in the service
    contract, reviews the content for the feed and copies the data as
    appropriate to the 'feeds' class.

    :param member: the membership of the service in the local pod
    :param listen_relation: the listen relation to get the 'destination_class'
    and the 'feeds' class from.
    :param cache_store: the cache store in the local pod where to retrieve
    and store data from/to
    :param tg: the task group to use for creating the new task
    :returns: None
    :raises: None
    '''

    schema: Schema = member.schema
    service_id: int = member.service_id

    # This listens to the events for the data class on the local pod
    # so that it can immediately start receive updates to changes
    # made in a remote pod that replicate to a local data class.
    # So the flow is:
    # 1: remote pod some data_class that is an array
    # 2: discover_worker on local pod, to 'destination class'
    # 3: feed_worker on local pod to 'feed class'
    class_name: str = listen_relation.class_name
    dest_class_name: str = listen_relation.destination_class
    dest_class: SchemaDataArray = schema.data_classes[dest_class_name]

    # This gets us the process ID so we can start listening to the
    # local pubsub socket for updates to the 'network_links' data class
    process_id: int = find_process_id(
        PubSubNng.get_directory(service_id)
    )

    _LOGGER.debug(
        f'Setting up pubsub for class {dest_class_name} '
        f'for process {process_id}'
    )

    pubsub = PubSubNng(dest_class, schema, False, False, process_id)

    feed_class_name: str = listen_relation.feed_class
    if not feed_class_name:
        _LOGGER.info(
            f'No feed class for this relation for class {class_name}'
        )
        return

    feed_class: SchemaDataArray = \
        schema.data_classes.get(listen_relation.feed_class)

    if not feed_class:
        _LOGGER.warning(
            f'We do not have class {feed_class_name} '
            f'for listen relation for {class_name}'
        )

    if not feed_class.cache_only:
        _LOGGER.warning(f'Feed class {feed_class.name} must be cache-only')
        return

    dest_ref_class: SchemaDataObject = dest_class.referenced_class
    dest_required_fields: set[str] = set(dest_ref_class.required_fields)
    feed_ref_class: SchemaDataObject = feed_class.referenced_class
    feed_required_fields: set[str] = set(feed_ref_class.required_fields)
    if not feed_required_fields.issubset(dest_required_fields):
        _LOGGER.warning(
            f'Required fields {feed_required_fields} in feed referenced class '
            f'{dest_ref_class.name} must all be required fields in the '
            f'destination class {dest_ref_class.name} with required fields '
            f'{dest_required_fields} for listen_relation for {class_name}'
        )
        return

    _LOGGER.info(
        f'Starting to listen for changes to class {dest_class_name} for '
        f'new content to store in {feed_class.name} for service {service_id}'
    )

    await get_feed_updates(server, pubsub, feed_class, member)


async def get_feed_updates(server: PodServer, pubsub: PubSubNng,
                           feed_class: SchemaDataArray, member: Member
                           ) -> None:
    '''
    Listens in the local pod to updates to the destination class specified in
    an 'ListenRelation', evaluates that content and then stores the content
    in the 'feed_class' specified by the ListenRelation

    :param pubsub: the pubsub object to use for listening to updates to
    the updates to network links in the local pod
    :param feed_class: the name of the data class to store received updates
    :param member: the membership of the local pod
    :param member: the membership of the service in the local pod
    :param tg: the task group that tasks for newly added remote pods should
    be created under
    '''

    last_updated = 0
    following: dict[UUID, set[str]] = {}
    while True:
        try:
            messages: list[PubSubMessage] = await pubsub.recv()
            if datetime.now(tz=UTC).timestamp() - last_updated > 60:
                network_links: list[NetworkLink] = \
                    await member.data.load_network_links()

                for link in network_links:
                    following[link.member_id] = link.annotations

            message: PubSubMessage
            for message in messages:
                await process_message(
                    message, server, member, pubsub.data_class,
                    feed_class.name, following
                )
        except Exception as exc:
            _LOGGER.exception(
                f'Update failure for append to {feed_class.name}: {exc}'
            )


async def process_message(message: PubSubMessage, server: PodServer,
                          member: Member, incoming_class: SchemaDataArray,
                          feed_class_name: str, following: dict[str, set[str]]
                          ) -> bool:
    '''
    Processes the message received from PubSub socket

    :param message: the message to process
    :param server:
    :param member: our membership
    :param feed_class: the class to store the data in
    :param pubsub: the pubsub object to use for sending data
    :returns: whether the message was processed or not
    '''

    if message.action != PubSubMessageAction.APPEND:
        _LOGGER.debug(
            f'Ignoring action {message.action.value} '
            f'for {message.class_name}'
        )
        return False

    _LOGGER.debug(
        f'Received data from class {message.class_name} of '
        f'service_id {member.service_id} for '
        f'asset ID {message.node.get("asset_id")}'
    )

    if message.origin_id not in following:
        _LOGGER.debug(
            f'Not following origin_id {message.origin_id} '
            f'for class {message.class_name} of '
            f'service_id {member.service_id}'
        )
        return False

    following_annotations: set[str] | None = following.get(
        message.origin_id
    )

    creator: str | None = message.node.get('creator')
    if (following_annotations
            and (creator not in following_annotations)):
        _LOGGER.debug(f'Not following creator: {creator}')
        return False

    # TODO: use HTTP call here so that counters for the feed class
    # get updated
    await MemberData.append_data(
        server, member, feed_class_name, message.node,
        message.origin_id, message.origin_id_type,
        message.origin_class_name
    )

    delete_filter_set = DataFilterSet.from_data_class_data(
        incoming_class.referenced_class, message.node
    )
    _LOGGER.debug(
        f'Deleting data from class {incoming_class} '
        f'with filter: {str(delete_filter_set)}'
    )

    await MemberData.delete_data(
        server, member, incoming_class, delete_filter_set
    )

    return True


def find_process_id(pubsub_dir: str = PubSubNng.PUBSUB_DIR) -> int:
    '''
    Finds the process ID of the process that is sending to the Nng socket
    '''

    process_id = None
    for file in os.listdir(pubsub_dir):
        if file.startswith('network_links.pipe'):
            process_id: str = file.split('-')[-1]
            _LOGGER.debug(f'Found app server process ID {process_id}')
            return int(process_id)

    raise RuntimeError(f'Could not find process ID from: {pubsub_dir}')


async def setup_account(argv) -> Account:
    data: dict[str, str] = get_environment_vars()

    debug: bool = data.get('debug', False)
    if debug and str(debug).lower() in ('true', 'debug', '1'):
        config.debug = True
        # Make our files readable by everyone, so we can
        # use tools like call_data_api.py to debug the server
        os.umask(0o0000)
    else:
        os.umask(0x0077)

    _LOGGER.debug(
        f'Starting feed_worker {data["bootstrap"]}: '
        f'daemonize: {data["daemonize"]}'
    )

    try:
        server: PodServer = PodServer(
            cloud_type=CloudType(data['cloud']),
            bootstrapping=bool(data.get('bootstrap')),
            db_connection_string=data.get('db_connection'),
            http_port=data['http_port'],
            host_root_dir=data['host_root_dir']
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
            DataStoreType.POSTGRES, account.data_secret
        )
        await server.set_cache_store(CacheStoreType.POSTGRES)

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
