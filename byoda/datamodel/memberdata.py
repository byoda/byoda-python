'''
Class for modeling an element of data of a member
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
import itertools

from uuid import UUID
from typing import TypeVar
from datetime import datetime
from datetime import timezone
from datetime import timedelta

from fastapi import Request

from strawberry.types import Info

from byoda import config

from byoda.datamodel.dataclass import SchemaDataArray
from byoda.datamodel.dataclass import SchemaDataObject
from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.graphql_proxy import GraphQlProxy
from byoda.datamodel.table import Table
from byoda.datamodel.pubsub_message import PubSubDataAppendMessage
from byoda.datamodel.pubsub_message import PubSubDataMutateMessage
from byoda.datamodel.pubsub_message import PubSubDataDeleteMessage

from byoda.datatypes import ORIGIN_KEY
from byoda.datatypes import IdType
from byoda.datatypes import MARKER_NETWORK_LINKS

from byoda.datastore.data_store import DataStore
from byoda.datacache.counter_cache import CounterCache
from byoda.datacache.counter_cache import CounterFilter

from byoda.requestauth.requestauth import RequestAuth

from byoda.secrets.secret import InvalidSignature

from byoda.storage import FileMode
from byoda.storage.pubsub import PubSub
from byoda.storage.pubsub import PubSubTech

from byoda.util.paths import Paths

from byoda.servers.pod_server import PodServer

from byoda.exceptions import ByodaValueError

# These imports are only used for typing
from .schema import Schema
from .dataclass import SchemaDataItem

Member = TypeVar('Member')

_LOGGER = logging.getLogger(__name__)

MAX_FILE_SIZE = 65536

RECURSIVE_QUERY_TTL = 300
QUERY_EXPIRATION = timedelta(seconds=RECURSIVE_QUERY_TTL)


class MemberData(dict):
    '''
    Generic data object for the storing data as defined
    by the schema of services
    '''

    def __init__(self, member: Member):
        self.member: Member = member
        self.unvalidated_data: dict = None

        self.paths: Paths = member.paths

    def initalize(self) -> None:
        '''
        Initializes the data for a new membership. Every service
        contract must include
        '''

        if 'member' in self:
            if self['member'].get('member_id'):
                raise ValueError('Member structure already exists')
        else:
            self['member'] = {}

        self['member']['member_id'] = str(self.member.member_id)
        self['member']['joined'] = datetime.now(timezone.utc).isoformat()

    def query(self, object_name: str, filters: DataFilterSet
              ) -> list[dict[str, object]]:
        '''
        Queries the data store for the given object and filters
        '''

        raise NotImplementedError

    def normalize(self) -> None:
        '''
        Updates data values to match data type as defined in JSON-Schema,
        ie. for UUIDs and datetime
        '''

        schema: Schema = self.member.service.schema

        if not schema:
            raise ValueError('Schema has not yet been loaded')

        data_classes: dict[str, SchemaDataItem] = schema.data_classes
        for field, value in self.items():
            if field not in data_classes:
                raise ValueError(
                    f'Found data field {field} not in the data classes '
                    'for the schema'
                )

            normalized = data_classes[field].normalize(value)
            self[field] = normalized

    def validate(self):
        '''
        Validates the unvalidated data against the schema
        '''

        try:
            if self.unvalidated_data:
                _LOGGER.debug(
                    f'Validating {len(self.unvalidated_data)} bytes of data'
                )
                self.member.schema.validator.is_valid(self.unvalidated_data)
            else:
                _LOGGER.debug('No unvalidated data to validate')
        except Exception as exc:
            _LOGGER.warning(
                'Failed to validate data for service_id '
                f'{self.member.service_id}: {exc}'
            )
            raise

    async def load_protected_shared_key(self) -> None:
        '''
        Reads the protected symmetric key from file storage. Support
        for changing symmetric keys is currently not supported.
        '''

        filepath = self.paths.get(
            self.paths.MEMBER_DATA_SHARED_SECRET_FILE
        )

        try:
            protected = await self.member.storage_driver.read(
                filepath, file_mode=FileMode.BINARY
            )
            self.member.data_secret.load_shared_key(protected)
        except OSError:
            _LOGGER.error(
                'Can not read the protected shared key for service %s from %s',
                self.member.service_id, filepath
            )
            raise

    async def save_protected_shared_key(self) -> None:
        '''
        Saves the protected symmetric key
        '''

        filepath = self.paths.get(self.paths.MEMBER_DATA_SHARED_SECRET_FILE)

        await self.member.storage_driver.write(
            filepath, self.member.data_secret.protected_shared_key,
            file_mode=FileMode.BINARY
        )

    async def load_network_links(self, relations: str | list[str] | None = None
                                 ) -> list[dict[str, str | datetime]]:
        '''
        Loads the network links for the membership. Used by the access
        control logic.
        '''

        filter_set = None
        if relations:
            # DataFilter logic uses 'and' logic when multiple filters are
            # specified. So we only use DataFilterSet when we have a single
            # relation to filter on.
            relation = relations
            if isinstance(relations, list) and len(relations) == 1:
                relation = relations[0]

            if isinstance(relation, str):
                link_filter = {
                    'relation': {
                        'eq': relation
                    }
                }
                filter_set = DataFilterSet(link_filter)

        data_store: DataStore = config.server.data_store

        data = await data_store.query(
            self.member.member_id, MARKER_NETWORK_LINKS,
            filters=filter_set
        )

        if relations and isinstance(relations, list) and len(relations) > 1:
            # If more than 1 relation was provided, then we filter here
            # ourselves instead of using DataFilterSet
            data = [
                network_link for network_link in data
                if network_link['relation'] in relations
            ]

        return data

    async def add_log_entry(self, request: Request, auth: RequestAuth,
                            operation: str, source: str, class_name: str,
                            filters: list[str] | DataFilterSet = None,
                            relations: list[str] = None,
                            remote_member_id: UUID | None = None,
                            depth: int = None, message: str = None,
                            timestamp: datetime | None = None,
                            origin_member_id: UUID | None = None,
                            origin_signature: str | None = None,
                            query_id: UUID = None,
                            signature_format_version: int | None = None
                            ) -> None:
        '''
        Adds an entry to data log
        '''

        data_store: DataStore = config.server.data_store

        if not isinstance(filters, DataFilterSet):
            filter_set = DataFilterSet(filters)
        else:
            filter_set = filters

        await data_store.append(
            self.member.member_id, 'datalogs',
            {
                'created_timestamp': datetime.now(timezone.utc),
                'remote_addr': request.client.host,
                'remote_id': auth.id,
                'remote_id_type': auth.id_type.value.rstrip('s-'),
                'operation': operation,
                'object': object,
                'query_filters': str(filter_set),
                'query_depth': depth,
                'query_relations': ', '.join(relations or []),
                'query_id': query_id,
                'query_remote_member_id': remote_member_id,
                'origin_member_id': origin_member_id,
                'origin_timestamp': timestamp,
                'origin_signature': origin_signature,
                'signature_format_version': signature_format_version,
                'source': source,
                'message': message,
            }
        )

    @staticmethod
    async def get_data(service_id: int, info: Info, depth: int = 0,
                       relations: list[str] = None,
                       filters: list[str] = None,
                       timestamp: datetime | None = None,
                       remote_member_id: UUID | None = None,
                       query_id: UUID | None = None,
                       origin_member_id: UUID | None = None,
                       origin_signature: bytes | None = None,
                       signature_format_version: int = 1,
                       ) -> dict[str, dict]:
        '''
        Extracts the requested data object.

        This function is called from the Strawberry code generated by the
        jsonschema-to-graphql converter

        :param service_id: the service being queried
        :param info: Info object with information about the GraphQL request
        :param relations: relations to proxy the request to
        :param timestamp: the timestamp for the original request
        :param filters: filters to apply to the collected data
        :returns: the requested data
        '''

        if not info.path:
            raise ByodaValueError('Did not get value for path parameter')

        if info.path.typename != 'Query':
            raise ByodaValueError(
                f'Got graphql invocation for "{info.path.typename}" '
                f'instead of "Query"'
            )

        _LOGGER.debug(
            f'Got graphql invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        server = config.server

        await server.account.load_memberships()
        member: Member = server.account.memberships[service_id]

        # If an origin_member_id has been provided then we check
        # the signature
        auth: RequestAuth = info.context['auth']
        if not await member.query_cache.set(query_id, auth.id):
            raise ValueError('Duplicate query id')

        if origin_member_id or origin_signature or timestamp:
            try:
                await GraphQlProxy.verify_signature(
                    service_id, relations, filters, timestamp,
                    origin_member_id, origin_signature
                )
            except InvalidSignature:
                raise ByodaValueError(
                    'Failed verification of signature for recursive query '
                    f'received from {auth.id} with IP {auth.remote_addr} '
                )

            timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp - datetime.now(timezone.utc) > QUERY_EXPIRATION:
                _LOGGER.debug(
                    'TTL of {RECURSIVE_QUERY_TTL} seconds expired, '
                    'not proxying this request'
                )
                depth = 0
        elif depth > 0:
            # If no origin_member_id has been provided then the request
            # must come from our own membership
            if (auth.id_type != IdType.MEMBER or
                    auth.member_id != member.member_id):
                raise ByodaValueError(
                    'Received a recursive query without signture '
                    'submitted by someone else than ourselves'
                )

        # For queries for objects we implement pagination and identify
        # those APIs by appending _connection to the name for the
        # data class
        class_name = info.path.key
        if class_name.endswith('_connection'):
            class_name = class_name[:-1 * len('_connection')]

        filter_set = DataFilterSet(filters)

        await member.data.add_log_entry(
            info.context['request'], info.context['auth'], 'get',
            'graphql', class_name, relations=relations, filters=filter_set,
            depth=depth, timestamp=timestamp,
            remote_member_id=remote_member_id,
            origin_member_id=origin_member_id,
            origin_signature=origin_signature,
            signature_format_version=signature_format_version,
            query_id=query_id,
        )

        all_data = []

        if depth:
            request: Request = info.context['request']
            query = await request.body()

            proxy = GraphQlProxy(member)
            if not origin_member_id:
                # Our membership submitted the query so let's
                # add needed data and sign the request
                origin_member_id = member.member_id
                timestamp = datetime.now(timezone.utc)

                origin_signature = proxy.create_signature(
                    service_id, relations, filters, timestamp,
                    origin_member_id
                )
                # We need to insert origin_member_id, origin_signature
                # and timestamp in the received query
                all_data = await proxy.proxy_request(
                    class_name, query, info, query_id, depth,
                    relations, origin_member_id=origin_member_id,
                    origin_signature=origin_signature,
                    timestamp=timestamp
                )
            else:
                # origin_member_id, origin_signature and timestamp must
                # already be set
                all_data = await proxy.proxy_request(
                    class_name, query, info, query_id, depth, relations
                )

            _LOGGER.debug(
                f'Collected {len(all_data)} items from the network'
            )

        data_store = server.data_store
        _LOGGER.debug('Collecting data')
        data = await data_store.query(member.member_id, class_name, filter_set)
        for data_item in data or []:
            data_item[ORIGIN_KEY] = member.member_id
            all_data.append(data_item)

        _LOGGER.debug(f'Got {len(data)} items of data')

        return all_data

    @staticmethod
    async def get_updates(service_id: int, info: Info,
                          filters: list[str] = None) -> dict[str, dict]:
        '''
        Provides updates if an array at the root level of the schema
        has been updated.

        This function is called from the Strawberry code generated by the
        jsonschema-to-graphql converter

        :param service_id: the service being queried
        :param info: Info object with information about the GraphQL request
        :param filters: filters to apply to the collected data
        :returns: the requested data
        '''

        if not info.path:
            raise ByodaValueError('Did not get value for path parameter')

        if info.path.typename != 'Subscription':
            raise ByodaValueError(
                f'Got graphql invocation for "{info.path.typename}" '
                f'instead of "Subscription"'
            )

        _LOGGER.debug(
            f'Got graphql invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        server: PodServer = config.server
        await server.account.load_memberships()
        member: Member = server.account.memberships[service_id]

        # The GraphQL API that was called, with other words, the name
        # of the class referenced by an array at the top-level of the
        # schema
        class_name = info.path.key[:-1 * len('_updates')]
        data_class = member.schema.data_classes[class_name]
        sub = PubSub.setup(
            data_class.name, data_class, member.schema,
            is_sender=False, pubsub_tech=PubSubTech.NNG
        )

        while True:
            messages = await sub.recv()

            filtered_data: list[dict] = []
            for message in messages or []:
                # We run the data through the filters but the filters
                # work on and return arrays
                filtered_items: list[dict] = DataFilterSet.filter(
                    filters, [message.data]
                )
                if filtered_items:
                    filtered_data.append(message)

            if filtered_data:
                return filtered_data

    @staticmethod
    async def get_counter(service_id: int, info: Info,
                          counter_filter: CounterFilter = None
                          ) -> int:
        '''
        Provides counters if an array at the root level of the schema
        has been updated.

        This function is called from the Strawberry code generated by the
        jsonschema-to-graphql converter

        :param service_id: the service being queried
        :param info: Info object with information about the GraphQL request
        :param filters: filters to apply to the collected data
        :returns: the requested data
        '''

        if not info.path:
            raise ByodaValueError('Did not get value for path parameter')

        if info.path.typename != 'Subscription':
            raise ByodaValueError(
                f'Got graphql invocation for "{info.path.typename}" '
                f'instead of "Subscription"'
            )

        _LOGGER.debug(
            f'Got graphql invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        server: PodServer = config.server
        await server.account.load_memberships()
        member: Member = server.account.memberships[service_id]

        # The GraphQL API that was called, with other words, the name
        # of the class referenced by an array at the top-level of the
        # schema
        class_name = info.path.key[:-1 * len('_counter')]
        data_class = member.schema.data_classes[class_name]
        sub = PubSub.setup(
            data_class.name, data_class, member.schema, is_sender=False
        )

        counter_cache: CounterCache = member.counter_cache
        data_store: DataStore = server.data_store
        table: Table = data_store.get_table(member.member_id, class_name)

        current_counter_value = await counter_cache.get(
            class_name, counter_filter, table
        )

        while True:
            messages = await sub.recv()

            for message in messages or []:
                # We run the data through the counter filters
                matches_filter = True
                if counter_filter:
                    for field_name, value in counter_filter.items():
                        if message.data.get(field_name) != value:
                            matches_filter = False

                if not matches_filter:
                    continue

                counter_value = await counter_cache.get(
                    class_name, counter_filter
                )

                if counter_value != current_counter_value:
                    return counter_value

    @staticmethod
    async def mutate_data(service_id, info: Info) -> None:
        '''
        Mutates the provided data

        :param service_id: Service ID for which the GraphQL API was called
        :param info: the Strawberry 'info' variable
        '''

        if not info.path:
            raise ValueError('Did not get value for path parameter')

        if info.path.typename != 'Mutation':
            raise ValueError(
                f'Got graphql invocation for "{info.path.typename}"" '
                f'instead of "Mutation"'
            )

        _LOGGER.debug(
            f'Got graphql mutation invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        server = config.server
        member = server.account.memberships[service_id]

        # By convention implemented in the Jinja template, the called mutate
        # 'function' starts with the string 'mutate' so we to find out
        # what mutation was invoked, we want what comes after it.
        class_object = info.path.key[len('mutate_'):].lower()

        await member.data.add_log_entry(
            info.context['request'], info.context['auth'], 'mutate',
            'graphql', class_object,
        )

        # Gets the data included in the mutation
        mutate_data: dict = info.selected_fields[0].arguments

        # Get the properties of the JSON Schema, we don't support
        # nested objects just yet
        schema = member.schema
        schema_properties = schema.json_schema['jsonschema']['properties']

        # TODO: refactor to use dataclasses
        properties = schema_properties[class_object].get('properties', {})

        data = {}
        for key in properties.keys():
            if properties[key]['type'] == 'object':
                raise ValueError(
                    'We do not support nested objects yet: %s', key
                )
            if properties[key]['type'] == 'array':
                raise ValueError(
                    'We do not support arrays yet'
                )
            if key.startswith('#'):
                _LOGGER.debug(
                    'Skipping meta-property %s in schema for service %s',
                    key, member.service_id
                )
                continue

            _LOGGER.debug(f'Setting key {key} for data object {class_object}')
            data[key] = mutate_data[key]

        _LOGGER.debug(
            f'Saving {len(data or [])} bytes of data after mutation of '
            f'{class_object}'
        )
        data_store: DataStore = server.data_store

        records_affected = await data_store.mutate(
            member.member_id, class_object, data
        )

        return records_affected

    @staticmethod
    async def update_data(service_id: int, filters, info: Info) -> int:
        '''
        Updates a dict in an array

        :param service_id: Service ID for which the GraphQL API was called
        :param info: the Strawberry 'info' variable
        '''

        if not info.path:
            raise ValueError('Did not get value for path parameter')

        if info.path.typename != 'Mutation':
            raise ValueError(
                f'Got graphql invocation for "{info.path.typename}" '
                f'instead of "Mutation"'
            )

        if not filters:
            raise ValueError(
                'Must specify one or more filters to select content for '
                'update'
            )

        _LOGGER.debug(
            f'Got graphql invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        # By convention implemented in the Jinja template, the called mutate
        # 'function' starts with the string 'update_' so we to find out
        # what mutation was invoked, we want what comes after it.
        class_key = info.path.key[len('update_'):].lower()

        server = config.server
        member = server.account.memberships[service_id]

        filter_set = DataFilterSet(filters)
        await member.data.add_log_entry(
            info.context['request'], info.context['auth'], 'update',
            'graphql', class_key, filters=filter_set
        )

        update_data: dict = info.selected_fields[0].arguments

        # 'filters' is a keyword that can't be used as the name of a field
        # in a schema
        update_data.pop('filters')

        updates = {
                key: value for key, value in update_data.items()
                if value is not None
            }

        _LOGGER.debug(
            f'Updating data for scalars {", ".join(updates.keys())} of'
            f'object {class_key}'
        )

        data_store: DataStore = server.data_store
        object_count = await data_store.mutate(
            member.member_id, class_key, updates, filter_set
        )

        data_class: SchemaDataArray = member.schema.data_classes[class_key]
        message = PubSubDataMutateMessage.create(object_count, data_class)
        pubsub_class: PubSub = data_class.pubsub_class
        await pubsub_class.send(message)

        _LOGGER.debug(
            f'Saving {len(updates or [])} fields of data after mutation of '
            f'{class_key}'
        )

        return object_count

    @staticmethod
    async def append_data(service_id, info: Info,
                          remote_member_id: UUID | None = None,
                          depth: int = 0) -> int:
        '''
        Appends the provided data

        :param service_id: Service ID for which the GraphQL API was called
        :param remote_member_id: member_id that submitted the request
        :param info: the Strawberry 'info' variable
        '''

        if not info.path:
            raise ValueError('Did not get value for path parameter')

        if info.path.typename != 'Mutation':
            raise ValueError(
                f'Got graphql invocation for "{info.path.typename}"" '
                f'instead of "Mutation"'
            )

        _LOGGER.debug(
            f'Got graphql mutation invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        server: PodServer = config.server
        member: Member = server.account.memberships[service_id]

        # By convention implemented in the Jinja template, the called
        # mutate 'function' starts with the string 'mutate' so to find out
        # what mutation was invoked, we want what comes after it.
        class_name = info.path.key[len('append_'):].lower()

        await member.data.add_log_entry(
            info.context['request'], info.context['auth'], 'append',
            'graphql', class_name, depth=depth,
            remote_member_id=remote_member_id
        )

        if remote_member_id and remote_member_id != member.member_id:
            _LOGGER.debug(
               'Received append request with remote member ID: '
               f'{remote_member_id}'
            )
            if depth != 1:
                raise ValueError(
                    'Must specify depth of 1 for appending to another '
                    'member'
                )
            request: Request = info.context['request']
            query = await request.body()
            proxy = GraphQlProxy(member)
            all_data = await proxy.proxy_request(
                class_name, query, depth, None, remote_member_id
            )
            return all_data
        else:
            _LOGGER.debug('Received append request with no remote member ID')

            if depth != 0:
                raise ValueError(
                    'Must specify depth = 0 for appending locally'
                )

            # Gets the data included in the mutation
            append_data: dict = info.selected_fields[0].arguments

            _LOGGER.debug(f'Appended {len(append_data or [])} items of data')
            data_store: DataStore = server.data_store
            object_count = await data_store.append(
                member.member_id, class_name, append_data
            )

            data_class: SchemaDataArray = \
                member.schema.data_classes[class_name]

            # Update the counter for the top-level array
            table: Table = data_store.get_table(member.member_id, class_name)
            counter_cache: CounterCache = member.counter_cache

            if data_class.referenced_class:
                keys: set[str] = MemberData._get_counter_key_permutations(
                    data_class, append_data
                )
            else:
                keys: set[str] = set([data_class.name])

            for key in keys:
                await counter_cache.update(key, 1, table, None)

            message = PubSubDataAppendMessage.create(append_data, data_class)
            pubsub_class: PubSub = data_class.pubsub_class
            await pubsub_class.send(message)

            return object_count

    @staticmethod
    async def delete_array_data(service_id: int, info: Info, filters) -> dict:
        '''
        Deletes one or more objects from an array.

        This function is called from the Strawberry code generated by the
        jsonschema-to-graphql converter
        '''

        if not info.path:
            raise ValueError('Did not get value for path parameter')

        if info.path.typename != 'Mutation':
            raise ValueError(
                f'Got graphql invocation for "{info.path.typename}" '
                f'instead of "Mutation"'
            )

        if not filters:
            raise ValueError(
                'Must specify one or more filters to select content for '
                'deletion'
            )

        _LOGGER.debug(
            f'Got graphql invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        # By convention implemented in the Jinja template, the called mutate
        # 'function' starts with the string 'delete_from' so we to find out
        # what mutation was invoked, we want what comes after it.
        class_name = info.path.key[len('delete_from_'):].lower()

        server = config.server
        member = server.account.memberships[service_id]

        filter_set = DataFilterSet(filters)
        await member.data.add_log_entry(
            info.context['request'], info.context['auth'], 'delete',
            'graphql', class_name=class_name, filters=filter_set
        )

        data_store: DataStore = server.data_store
        object_count: int = await data_store.delete(
            member.member_id, class_name, filter_set
        )

        table: Table = data_store.get_table(member.member_id, class_name)
        counter_cache: CounterCache = member.counter_cache

        data_class: SchemaDataArray = member.schema.data_classes[class_name]
        referenced_class: SchemaDataObject = data_class.referenced_class
        if not referenced_class:
            # Edge case for when the top-level array stores scalars instead
            # of objects
            return object_count

        # We need to see if any of the filters are for fields that are
        # counters and update the counters for those fields. This means that
        # field-specific counters are only decremented if the delete GraphQL
        # command specified the counter field in the filter.
        # HACK: this means that counters will not be properly decremented if
        # a filter was not specified for a counter field. Because of this
        # reason, the podworker will have to periodically check value for
        # the field-specific counters
        filter_data = {}
        for field in referenced_class.fields.values():
            if not field.is_counter:
                continue
            data_filter = getattr(filters, field.name, None)
            filter_value = getattr(data_filter, 'eq', None)
            if data_filter and filter_value:
                filter_data[field.name] = filter_value

        await MemberData._update_field_counters(
                -1 * object_count, filter_data, data_class,
                counter_cache, table
        )

        message = PubSubDataDeleteMessage.create(object_count, data_class)
        pubsub_class: PubSub = data_class.pubsub_class
        await pubsub_class.send(message)

        return object_count

    @staticmethod
    async def _update_field_counters(delta: int, data: dict,
                                     data_class: SchemaDataArray,
                                     counter_cache: CounterCache, table: Table
                                     ):
        '''
        Update the counter cache for any fields in the SchemaDataArray that
        are counters

        :param delta: The amount to increment the counter by (can be negative)
        :param data: the data provided in the query. Only counters for fields
        for which data is provided can be updated.
        :param data_class: The data class for the array for which the counters
        should be updated
        :param counter_cache: the cache where the key/values are stored
        :param table: the (SQL) table that can be queried if there is no
        existing value in the cache to start with
        '''

        # TODO: create test cases for this code
        keys = MemberData._get_counter_key_permutations(data_class, data)
        for key in keys:
            _LOGGER.debug(f'Updating counter {key} for append')
            await counter_cache.update(key, delta, table)

    @staticmethod
    def _get_counter_key_permutations(data_class: SchemaDataArray, data: set
                                      ) -> set[str]:
        '''
        Gets the different key permutations for the fields with the is_counter
        property set to True and for which a key/value exists in the data

        :param data_class: The data class for the array for which the keys
        should be generated
        :param data: the data provided in the query. Only counters for fields
        that have a value in the data will be included in the keys
        '''

        referenced_class: SchemaDataObject = data_class.referenced_class
        counter_fields = []
        if referenced_class:
            counter_fields = [
                field.name for field in referenced_class.fields.values()
                if field.is_counter and (not data or data.get(field.name))
            ]

        subsets = set()
        for index in range(1, len(counter_fields) + 1):
            sets = itertools.combinations(counter_fields, index)
            for key in sets:
                subsets.add(key)

        keys: set[str] = set()
        for combo in subsets:
            value: str = data_class.name
            for field in combo:
                # We can only manage keys for fields that are counters
                # if a value is provided for the field in the data.
                # This means counters do not have to be accurate but
                # we accept that to avoid having to query the database
                if field in data:
                    value += f'_{field}={data[field]}'

            keys.add(value.rstrip('-'))

        # We always have a key for the array
        keys.add(data_class.name)

        return keys
