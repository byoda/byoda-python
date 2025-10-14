'''
Various utility classes, variables and functions

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import os

from uuid import UUID
from datetime import UTC
from datetime import datetime
from logging import Logger
from logging import getLogger

from anyio.abc import TaskGroup

from byoda.datamodel.account import Account
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.schema import ListenRelation
from byoda.datamodel.pubsub_message import PubSubMessage
from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.table import ResultData
from byoda.datamodel.table import QueryResult
from byoda.datamodel.table import QueryResults

from byoda.models.data_api_models import NetworkLink
from byoda.models.data_api_models import UpdatesResponseModel

from byoda.datatypes import IdType
from byoda.datatypes import MARKER_NETWORK_LINKS
from byoda.datatypes import PubSubMessageAction

from byoda.storage.pubsub_nng import PubSubNng

from byoda.datastore.data_store import DataStore

from byoda.servers.pod_server import PodServer

from byoda.util.updates_listener import UpdateListenerMember
from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.util.paths import Paths
from byoda import config

from byoda.util.test_tooling import is_test_uuid

_LOGGER: Logger = getLogger(__name__)


async def get_current_network_links(account: Account, data_store: DataStore
                                    ) -> dict[UUID, UpdateListenerMember]:
    '''
    Gets the current network links of the local pod to create the initial
    set of remote pods to listen to

    :param member: the membership of the service in the local pod
    :returns: a list of UpdatesListener objects
    '''

    _LOGGER.debug(
        'Getting current local network links from '
        f'{len(account.memberships)} memberships'
    )

    log_extra: dict[str, int] = {}

    updates_listeners: dict[UUID, UpdateListenerMember] = {}
    member: Member
    for service_id, member in account.memberships.items():
        log_extra['service_id'] = service_id
        schema: Schema = member.schema
        listen_relations: list[ListenRelation] = schema.listen_relations
        if not listen_relations:
            _LOGGER.debug(
                f'No listen relations defined for service {service_id}'
            )
            continue

        _LOGGER.debug(
            f'Found {len(listen_relations)} listen relations',
            extra=log_extra
        )

        for listen_relation in listen_relations or []:
            wanted_relations: list[str] = listen_relation.relations or []
            listen_class: SchemaDataArray = \
                schema.data_classes[listen_relation.class_name]
            dest_class_name: str = listen_relation.destination_class

            # BUG: we currently support only one listen relation per service
            # otherwise we need have a dict
            # listeners[remote_member_id][source_class][dest_class]
            member_listeners: dict[UUID, UpdateListenerMember] = \
                await get_network_links_listeners(
                    data_store, member, wanted_relations,
                    listen_class, dest_class_name
                )

            if member.member_id in member_listeners:
                _LOGGER.debug('We never listen to ourselves')
                member_listeners.pop(member.member_id, None)

            updates_listeners |= member_listeners

    _LOGGER.debug(
        f'Have {len(updates_listeners)} current network links',
        extra=log_extra
    )
    return updates_listeners


async def get_all_network_links(data_store: DataStore, member: Member
                                ) -> QueryResults:
    '''
    Gets the network links for a member
    '''

    schema: Schema = member.schema
    data_class: SchemaDataArray = schema.data_classes.get(MARKER_NETWORK_LINKS)
    if not data_class:
        # Service without network_links does not have links to follow
        return []

    data: list[QueryResult] = await data_store.query(
        member_id=member.member_id, data_class=data_class, filters={}
    )

    return data


async def check_network_links(server: PodServer) -> None:
    '''
    Checks for all services if the remote members that we have a network link
    to are still up running
    '''

    account: Account = server.account
    data_store: DataStore = server.data_store

    _LOGGER.info('Checking health of network links')

    member: Member
    for member in account.memberships.values():
        await check_network_links_for_service(data_store, member)


async def check_network_links_for_service(data_store: DataStore,
                                          member: Member) -> None:
    '''
    Checks for a service if the remote members that we have a network link
    to are still up running
    '''

    schema: Schema = member.schema
    data_class: SchemaDataArray = schema.data_classes.get(
        MARKER_NETWORK_LINKS
    )
    if not data_class:
        # Service does not have a 'network_links' data class so
        # no need to check links
        return

    _LOGGER.debug(
        f'Checking status of existing network links for '
        f'member {member.member_id} of service {member.service_id}'
    )

    links: QueryResults = await get_all_network_links(data_store, member)

    now: float = datetime.now(tz=UTC).timestamp()

    paths: Paths = member.paths
    links_healthy: dict[UUID, bool] = {}
    for link, _ in links or []:
        remote_member_id: dict = link['member_id']
        if is_test_uuid(remote_member_id):
            continue

        if remote_member_id not in links_healthy:
            try:
                result: HttpResponse = await ApiClient.call(
                    paths.PODHEALTH_API, method='GET',
                    secret=member.tls_secret, service_id=member.service_id,
                    member_id=remote_member_id, timeout=1
                )

                links_healthy[remote_member_id] = result.status_code == 200
            except Exception:
                links_healthy[remote_member_id] = False

        if links_healthy[remote_member_id]:
            # This data filter will cause each link we have with a remote
            # member to be updated
            data_filter: DataFilterSet = DataFilterSet(
                {'member_id': {'eq': remote_member_id}}
            )
            link['last_health_api_success'] = now
            cursor: str = data_class.get_cursor_hash(link, member.member_id)
            await data_store.mutate(
                member.member_id, data_class.name, link, cursor,
                data_filter_set=data_filter, origin_id=member.member_id,
                origin_id_type=IdType.MEMBER
            )


async def get_network_links_listeners(data_store: DataStore, member: Member,
                                      wanted_relations: list[str],
                                      listen_class: SchemaDataArray,
                                      dest_class_name: str,
                                      ) -> dict[UUID, UpdateListenerMember]:
    '''
    Gets the listeners for the network links of a member matching the wanted
    relations
    '''

    service_id: int = member.service_id
    member_id: UUID = member.member_id
    log_extra: dict[str, str | int | UUID] = {
        'member_id': member_id,
        'service_id': service_id,
        'listen_class': listen_class.name,
        'dest_class': dest_class_name,
        'wanted_relations': ', '.join(wanted_relations or '(any)'),
    }
    _LOGGER.debug(
        f'Adding existing network links to store type {type(data_store)}',
        extra=log_extra
    )

    # TODO: Data filters do not yet support multiple specifications of the
    # same field so we have to filter ourselves
    data: QueryResults = await get_all_network_links(data_store, member)

    network_links: list[ResultData] = [
        edge_data for edge_data, _ in data or []
        if (not wanted_relations
            or edge_data['relation'] in wanted_relations)
    ]

    log_extra['all_network_links'] = len(data or [])
    log_extra['filtered_network_links'] = len(network_links)

    listeners: dict[UUID, UpdateListenerMember] = {}
    link: ResultData
    for link in network_links:
        try:
            remote_member_id: UUID = link.get('member_id')
            log_extra['remote_member_id'] = remote_member_id
            if not isinstance(remote_member_id, UUID):
                remote_member_id = UUID(remote_member_id)
            log_extra['remote_member_id'] = remote_member_id
        except (TypeError, ValueError) as exc:
            _LOGGER.debug(
                f'Network link has invalid member_id, skipping: {exc}',
                extra=log_extra
            )
            continue

        if remote_member_id not in listeners:
            annotations: list[str] = link.get('annotations') or []
            _LOGGER.debug('Adding listener', extra=log_extra)
            listener: UpdateListenerMember = await UpdateListenerMember.setup(
                listen_class.name, member, remote_member_id, dest_class_name,
                annotations
            )
            if config.debug:
                # In debug mode we get all assets from the pods we follow
                # await listener.get_all_data()
                pass

            listeners[listener.remote_member_id] = listener

    _LOGGER.debug('Found existing network links', extra=log_extra)

    return listeners


async def listen_local_network_links_tables(
        account: Account, existing_listeners: dict[UUID, UpdateListenerMember],
        task_group: TaskGroup) -> None:
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

    log_extra: dict[str, str | int | UUID] = {}

    member: Member
    for member in account.memberships.values():
        service_id: int = member.service_id
        log_extra['service_id'] = service_id
        log_extra['member_id'] = member.member_id
        schema: Schema = member.schema

        # This gets us the process ID so we can start listening to the
        # local pubsub socket for updates to the 'network_links' data class
        process_id: int = find_process_id(PubSubNng.get_directory(service_id))
        log_extra['process_id'] = process_id

        # This listens to the events for network_links of a service on the
        # local pod so that it can immediately start following a remote pod
        data_class: SchemaDataArray = schema.data_classes[MARKER_NETWORK_LINKS]
        pubsub = PubSubNng(
            data_class=data_class, schema=schema, is_counter=False,
            is_sender=False, process_id=process_id
        )

        listen_relations: list[ListenRelation] = schema.listen_relations
        for listen_relation in listen_relations:
            # TODO: for now relations must be the same for each listen_relation
            class_name: str = listen_relation.class_name
            relations: list[str] = listen_relation.relations
            dest_class_name: str = listen_relation.destination_class

            log_extra['src_class_name'] = class_name
            log_extra['dest_class_name'] = dest_class_name
            log_extra['relations'] = ','.join(relations) or '(any)'
            _LOGGER.info(
                'Starting to listen for changes for new relations',
                extra=log_extra
            )
            task_group.start_soon(
                get_network_link_updates, pubsub, class_name, dest_class_name,
                member, relations, task_group, existing_listeners
            )


async def get_network_link_updates(
        pubsub: PubSubNng, listen_class_name: str, dest_class_name: str,
        member: Member, relations: list[str], task_group: TaskGroup,
        existing_listeners: dict[UUID, UpdateListenerMember]) -> None:
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

    log_extra: dict[str, any] = {
        'listen_class': listen_class_name,
        'dest_class': dest_class_name,
        'member_id': member.member_id,
        'service_id': member.service_id,
        'relations': ', '.join(relations) or '(any)'

    }

    # TODO: we also need logic to handle updated and deleted network links
    while True:
        try:
            messages: list[PubSubMessage] = await pubsub.recv()
            message: PubSubMessage
            for message in messages:
                resp: UpdatesResponseModel = review_message(message, relations)
                if not resp:
                    continue

                remote_member_id: UUID = resp.node.member_id
                log_extra['remote_member_id'] = remote_member_id

                service_id: int = member.service_id
                if (remote_member_id in existing_listeners and
                        existing_listeners[remote_member_id].matches(
                        remote_member_id, service_id, listen_class_name,
                        dest_class_name)):
                    _LOGGER.debug(
                        'Already connected to remote pod', extra=log_extra
                    )
                    return None

                # New listener for a new remote pod
                _LOGGER.debug('Initiating connection to pod', extra=log_extra)
                listener: UpdateListenerMember = \
                    await UpdateListenerMember.setup(
                        listen_class_name, member, remote_member_id,
                        dest_class_name, resp.node.annotations
                    )
                task_group.start_soon(listener.get_updates)
                existing_listeners[remote_member_id] = listener
        except Exception as exc:
            _LOGGER.warning(
                'Update failure for append', extra={'exception': str(exc)}
            )


def review_message(message: PubSubMessage, relations: list[str]
                   ) -> UpdatesResponseModel | None:
    '''
    validates the received message and sees if the network link in the
    message is one of the relations that we're following

    :param message: the message to review
    :returns: message if it should be processed, None otherwise
    :raises:
    '''

    log_extra: dict[str, any] = {
        'message_class': message.class_name,
        'origin_class': message.origin_class_name,
        'origin_id': message.origin_id,
        'origin_id_type': message.origin_id_type,
        'cursor': message.cursor,
        'action': message.action.value
    }
    if message.action != PubSubMessageAction.APPEND:
        _LOGGER.info('Ignoring action', extra=log_extra)
        return None

    try:
        link_data: dict[str, str | UUID | datetime] = message.node
        resp = UpdatesResponseModel(
            origin_class_name=message.class_name,
            origin_id=message.origin_id,
            origin_id_type=message.origin_id_type,
            cursor=message.cursor,
            node=link_data
        )
        link = NetworkLink(**resp.node)
        resp.node = link
        log_extra['relation'] = link.relation
        log_extra['remote_member_id'] = link.member_id
    except Exception as exc:
        _LOGGER.debug(
            f'Received invalid update message for a network link: {exc}',
            extra=log_extra
        )
        return None

    _LOGGER.debug('Received update')

    if resp.origin_class_name != MARKER_NETWORK_LINKS:
        _LOGGER.debug(
            f'We received an updated for the wrong class: '
            f'{resp.origin_class_name}', extra=log_extra
        )
        return None

    if relations and link.relation not in relations:
        _LOGGER.debug(
            'Relation not in relations we are tracking', extra=log_extra
        )
        return None

    return resp


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
