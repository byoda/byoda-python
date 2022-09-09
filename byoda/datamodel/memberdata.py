'''
Class for modeling an element of data of a member
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
import orjson
from uuid import UUID
from typing import TypeVar
from copy import copy, deepcopy
from datetime import datetime
from datetime import timezone
from datetime import timedelta

from fastapi import Request

from strawberry.types import Info

from byoda import config

from byoda.datamodel.datafilter import DataFilterSet
from byoda.datamodel.graphql_proxy import GraphQlProxy

from byoda.datatypes import ORIGIN_KEY
from byoda.datatypes import IdType

from byoda.datastore.document_store import DocumentStore

from byoda.requestauth.requestauth import RequestAuth

from byoda.secrets.secret import InvalidSignature

from byoda.storage import FileMode

from byoda.util.paths import Paths

from byoda.exceptions import ByodaValueError

# These imports are only used for typing
from .schema import Schema
from .dataclass import SchemaDataItem

Member = TypeVar('Member')

_LOGGER = logging.getLogger(__name__)

MAX_FILE_SIZE = 65536

RECURSIVE_QUERY_TTL = 300


class MemberData(dict):
    '''
    Generic data object for the storing data as defined
    by the schema of services
    '''

    def __init__(self, member: Member, paths: Paths,
                 doc_store: DocumentStore):
        self.member: Member = member
        self.unvalidated_data: dict = None

        self.paths: Paths = paths

        self.document_store: DocumentStore = doc_store

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

    async def load(self) -> None:
        '''
        Load the data from the data store
        '''

        filepath = self.paths.get(
            self.paths.MEMBER_DATA_PROTECTED_FILE,
            service_id=self.member.service_id
        )

        try:
            data = await self.document_store.read(
                filepath, self.member.data_secret
            )
            for key, value in data.items():
                self[key] = value

            _LOGGER.debug(f'Loaded {len(self or [])} items')

        except FileNotFoundError:
            _LOGGER.warning(
                'Unable to read data file for service '
                f'{self.member.service_id} from {filepath}'
            )
            return {}

        return self.normalize()

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

    async def save(self, data=None) -> None:
        '''
        Save the data to the data store
        '''

        # MemberData inherits from dict so has a length
        if not len(self) and not data:
            raise ValueError(
                'No member data for service %s available to save',
                self.member.service_id
            )

        try:
            if data:
                self.unvalidated_data = data
            else:
                data = {}
                self.unvalidated_data = data

            self.validate()

            # TODO: properly serialize data
            await self.document_store.write(
                self.paths.get(
                    self.paths.MEMBER_DATA_PROTECTED_FILE,
                    service_id=self.member.service_id
                ),
                data,
                self.member.data_secret
            )
            _LOGGER.debug(f'Saved {len(self.keys() or [])} items')

            # We need to update our dict with the data passed to this
            # method
            if self.unvalidated_data:
                for key, value in data.items():
                    self[key] = value

        except OSError:
            _LOGGER.error(
                'Unable to write data file for service %s',
                self.member.service_id
            )

    def _load_from_file(self, filename: str) -> None:
        '''
        This function should only be used by test cases
        '''

        with open(filename) as file_desc:
            raw_data = file_desc.read(MAX_FILE_SIZE)

        self.unvalidated_data = orjson.loads(raw_data)

    def validate(self):
        '''
        Validates the unvalidated data against the schema
        '''

        try:
            if self.unvalidated_data:
                self.member.schema.validator.is_valid(self.unvalidated_data)
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

    async def add_log_entry(self, request: Request, auth: RequestAuth,
                            operation: str, source: str, object: str,
                            filters: list[str] = None,
                            relations: list[str] = None,
                            remote_member_id: UUID | None = None,
                            depth: int = None, message: str = None,
                            timestamp: datetime | None = None,
                            origin_member_id: UUID | None = None,
                            origin_signature: str | None = None,
                            query_id: UUID = None,
                            signature_format_version: int | None = None,
                            load_data=False, save_data: bool = True):
        '''
        Adds an entry to data log
        '''

        if load_data:
            await self.load()

        if 'datalogs' not in self:
            self['datalogs'] = []

        filter_set = DataFilterSet(filters)

        self['datalogs'].append(
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

        if save_data:
            await self.save()

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
        member: Member = server.account.memberships[service_id]
        await member.load_data()

        # For queries for objects we implement pagination and identify
        # those APIs by appending _connection to the name for the
        # data class
        key = info.path.key
        if key.endswith('_connection'):
            key = key[:-1 * len('_connection')]

        # If an origin_member_id has been provided then we check
        # the signature
        auth: RequestAuth = info.context['auth']
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

            delta = timedelta(seconds=RECURSIVE_QUERY_TTL)
            timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp - datetime.now(timezone.utc) > delta:
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

        await member.data.add_log_entry(
            info.context['request'], info.context['auth'], 'get',
            'graphql', key, relations=relations, filters=filters,
            depth=depth, timestamp=timestamp,
            remote_member_id=remote_member_id,
            origin_member_id=origin_member_id,
            origin_signature=origin_signature,
            signature_format_version=signature_format_version,
            query_id=query_id,
            save_data=True
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
                    key, query, info, depth, relations,
                    origin_member_id=origin_member_id,
                    origin_signature=origin_signature,
                    timestamp=timestamp
                )
            else:
                # origin_member_id, origin_signature and timestamp must
                # already be set
                all_data = await proxy.proxy_request(
                    key, query, info, depth, relations
                )

            _LOGGER.debug(
                f'Collected {len(all_data)} items from the network'
            )

        # DataFilterSet works on lists so we make put the object in a list
        data = member.data.get(key)
        if isinstance(data, dict):
            data = [data]

        if filters:
            if isinstance(data, list):
                filtered_data = DataFilterSet.filter(filters, data)
            else:
                _LOGGER.warning(
                    'Received query with filters for data that is not a list: '
                    f'{member.data}'
                )
        else:
            filtered_data = data

        _LOGGER.debug(
            f'Got {len(filtered_data or [])} filtered objects out '
            f'of {len(data or [])} locally'
        )

        modified_data = deepcopy(filtered_data)
        for item in modified_data or []:
            item[ORIGIN_KEY] = member.member_id

        all_data.extend(modified_data or [])

        return all_data

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

        # Any data we may have in memory may be stale when we run
        # multiple processes so we always need to load the data
        await member.load_data()

        # We do not modify existing data as it will need to be validated
        # by JSON Schema before it can be accepted.
        data = copy(member.data)

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

        # The query may be for an object for which we do not yet have
        # any data
        if class_object not in member.data:
            member.data[class_object] = dict()

        # TODO: refactor to use dataclasses
        properties = schema_properties[class_object].get('properties', {})

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
            member.data[class_object][key] = mutate_data[key]

        _LOGGER.debug(f'Saving data after mutation of {class_object}')
        await member.save_data(data)

        return member.data

    @staticmethod
    async def update_data(service_id: int, filters, info: Info) -> dict:
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
        class_object = info.path.key[len('update_'):].lower()

        server = config.server
        member = server.account.memberships[service_id]
        await member.load_data()

        await member.data.add_log_entry(
            info.context['request'], info.context['auth'], 'update',
            'graphql', class_object, filters=filters
        )

        data = copy(member.data.get(class_object))

        if not data:
            _LOGGER.debug(f'No data available for {class_object}')
            return {}

        if not isinstance(data, list):
            _LOGGER.warning(
                'Received query with filters for data that is not a list: '
                f'{member.data}'
            )

        # We remove the data based on the filters and then
        # add the data back to the list
        (data, removed) = DataFilterSet.filter_exclude(
            filters, data
        )
        _LOGGER.debug(
            f'Filtering left {len(data or [])} items and removed '
            f'{len(removed or [])}'
        )

        # We can update only one list item per query
        if not removed or len(removed) == 0:
            raise ValueError('filters did not match any data')
        elif len(removed) > 1:
            raise ValueError('filters match more than one record')

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
            f'object {class_object}'
        )

        removed[0].update(updates)

        data.append(removed[0])

        member.data[class_object] = data

        await member.save_data(member.data)

        return removed[0]

    async def append_data(service_id, info: Info,
                          remote_member_id: UUID | None = None,
                          depth: int = 0) -> dict:
        '''
        Appends the provided data

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

        # By convention implemented in the Jinja template, the called
        # mutate 'function' starts with the string 'mutate' so we to find out
        # what mutation was invoked, we want what comes after it.
        key = info.path.key[len('append_'):].lower()

        await member.data.add_log_entry(
            info.context['request'], info.context['auth'], 'append',
            'graphql', key, depth=depth, remote_member_id=remote_member_id
        )

        if remote_member_id and remote_member_id != member.member_id:
            if depth != 1:
                raise ValueError(
                    'Must specify depth of 1 for appending to another '
                    'member'
                )
            request: Request = info.context['request']
            query = await request.body()
            proxy = GraphQlProxy(member)
            all_data = await proxy.proxy_request(
                key, query, depth, None, remote_member_id
            )
            return all_data
        else:
            if depth != 0:
                raise ValueError(
                    'Must specify depth = 0 for appending locally'
                )

            # Any data we may have in memory may be stale when we run
            # multiple processes so we always need to load the data
            await member.load_data()

            # We do not modify existing data as it will need to be validated
            # by JSON Schema before it can be accepted.
            data = copy(member.data)

            # Gets the data included in the mutation
            mutate_data: dict = info.selected_fields[0].arguments

            # The query may be for an array for which we do not yet have
            # any data
            if key not in member.data:
                _LOGGER.debug(f'Initiating array {key} to empty list')
                member.data[key] = []

            # Strawberry passes us data that we can just copy as-is
            _LOGGER.debug(f'Appending item to array {key}')

            member.data[key].append(mutate_data)

            await member.save_data(data)

            return mutate_data

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
        class_object = info.path.key[len('delete_from_'):].lower()

        server = config.server
        member = server.account.memberships[service_id]
        await member.load_data()

        await member.data.add_log_entry(
            info.context['request'], info.context['auth'], 'delete',
            'graphql', object=class_object, filters=filters
        )

        data = copy(member.data.get(class_object))

        if not data:
            _LOGGER.debug(
                'Can not delete items from empty array for class '
                f'{class_object}'
            )
            return {}

        if not isinstance(data, list):
            _LOGGER.warning(
                'Received query with filters for data that is not a list: '
                f'{member.data}'
            )

        (data, removed) = DataFilterSet.filter_exclude(filters, data)

        _LOGGER.debug(
            f'Removed {len(removed or [])} items from array {class_object}, '
            f'keeping {len(data or [])} items'
        )

        member.data[class_object] = data

        await member.save_data(member.data)

        return removed
