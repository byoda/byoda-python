'''
Class for modeling permissions specified in the JSON Schema used
for generating the GraphQL Strawberry code based on Jinja2
templates

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging
from typing import TypeVar

from byoda.datatypes import RightsEntityType
from byoda.datatypes import DataOperationType

from byoda import config

_LOGGER = logging.getLogger(__name__)

RequestAuth = TypeVar('RequestAuth')
Member = TypeVar('Member')
Account = TypeVar('Account')


class DataAccessRight:
    '''
    Models a permission for a entity listed under the '#accesscontrol'
    of an object in the service contract / JSON Schema
    '''

    def __init__(self, permission_data: str | dict):
        self.distance: int | None = None
        self.relations: set(str) | None = None
        self.source_signature_required: bool | None = None
        self.anonimized_responses: bool | None = None
        self.search_condition: str | None = None
        self.search_match: str | None = None
        self.search_casesensitive: bool | None = None

        if isinstance(permission_data, str):
            self.data_operation: DataOperationType = \
                DataOperationType(permission_data)
            return

        self.data_operation: DataOperationType = \
            DataOperationType(permission_data['permission'])

        self.distance = permission_data.get('distance', 0)

        # Relations are converted to lower case
        relations = permission_data.get('relation')
        if isinstance(relations, str):
            self.relations = set(relations.lower())
        else:
            self.relations = [
                relation.lower() for relation in relations or []
            ]

        self.source_signature_required = \
            permission_data.get('source_signature_required')
        self.anonimized_responses = permission_data.get('anonimized_responses')

        if self.data_operation == DataOperationType.SEARCH:
            if (self.distance or self.relations or
                    self.source_signature_required or
                    self.anonimized_responses):
                raise ValueError(
                    'Search right cannot have other '
                    'parameters than the permission'
                )
            self.search_condition = permission_data.get('match', 'exact')
            self.casesensitive = permission_data.get('casesensitive', True)

    @staticmethod
    def get_access_rights(entity_type_data: str, permission_data: str | dict
                          ) -> tuple[RightsEntityType, list]:
        '''
        Factory for DataAccessRight

        returns: tuple of RightsEntityType and list of DataAccessRights
        '''

        entity_type: RightsEntityType = RightsEntityType(entity_type_data)

        permissions = list()
        for action in permission_data['permissions']:
            if entity_type == RightsEntityType.MEMBER:
                permission = MemberDataAccessRight(action)
            elif entity_type == RightsEntityType.NETWORK:
                permission = NetworkDataAccessRight(action)
            elif entity_type == RightsEntityType.SERVICE:
                permission = ServiceDataAccessRight(action)
            elif entity_type == RightsEntityType.ANY_MEMBER:
                permission = AnyMemberDataAccessRight(action)
            elif entity_type == RightsEntityType.ANONYMOUS:
                permission = AnonymousDataAccessRight(action)

            permissions.append(permission)

        _LOGGER.debug(f'Access right for {entity_type} is {permissions}')
        return entity_type, permissions

    async def authorize(self, service_id: int, operation: DataOperationType,
                        depth: int) -> tuple[bool | None, Member | None]:
        '''
        Returns our membership for the service if the operation matches
        this access right

        :param service_id: the requested ID of the service
        :param operation: the requested operation to authorize
        :param depth: the requested depth of recursion
        :returns: tuple of bool and Member. the bool may be None if the
        requested operation does not match this instance of the class
        derived from DataAccessRight. bool will be Fals if the requested
        recursion depth exceeds to 'distance' for the access right.
        '''

        account: Account = config.server.account

        if self.data_operation != operation:
            return None, None

        if self.distance and depth > self.distance:
            _LOGGER.debug(
                f'Requested recursion depth of {depth} exceeds the max '
                f'distance of {self.distance} for {operation} on {service_id}')
            return False, None

        await account.get_memberships()
        member: Member = account.memberships.get(service_id)

        return True, member


class MemberDataAccessRight(DataAccessRight):
    async def authorize(self, auth: RequestAuth, service_id: int,
                        operation: DataOperationType, depth: int) -> bool:
        '''
        Authorizes GraphQL API requests by ourselves

        :param auth: the object with info about the authentication of the
        client
        :param service_id: service membership that received the GraphQL API
        request
        :param operation: the requested operation
        :returns: whether this access right authorizes the requested
        operation. A False return does not mean that the operation is not
        authorized, it just means that this access right does not authorize
        it
        '''

        _LOGGER.debug('Authorizing member access for data item')

        allowed, member = await super().authorize(service_id, operation, depth)
        if allowed is False:
            _LOGGER.debug('Request not authorized')

        if not member:
            _LOGGER.debug(f'This pod is not a member of service {service_id}')
            return False

        if auth.member_id and auth.member_id == member.member_id:
            _LOGGER.debug(
                f'Authorization success for ourselves: {auth.member_id}'
            )
            return True

        _LOGGER.debug(f'{auth.member_id} is not ourselves: {member.member_id}')
        return False


class AnyMemberDataAccessRight(DataAccessRight):
    async def authorize(self, auth: RequestAuth, service_id: int,
                        operation: DataOperationType, depth: int) -> bool:
        '''
        Authorizes GraphQL API requests by any member of the service

        :param auth: the object with info about the authentication of the
        client
        :param service_id: service membership that received the GraphQL API
        request
        :param operation: the requested operation
        :returns: whether this access right authorizes the requested
        operation. A False return does not mean that the operation is not
        authorized, it just means that this access right does not authorize
        it
        '''

        _LOGGER.debug('Authorizing any member access for data item')

        allowed, member = await super().authorize(service_id, operation, depth)
        if allowed is False:
            _LOGGER.debug('Request not authorized')

        if not member:
            _LOGGER.debug(f'This pod is not a member of service {service_id}')
            return False

        if auth.member_id and auth.service_id == service_id:
            _LOGGER.debug(
                'Authorization success for any member of the service: '
                f'{auth.member_id}'
            )
            return True

        _LOGGER.debug(
            'Authorization failed for any member of the service: '
            f'{auth.member_id}'
        )

        return False


class NetworkDataAccessRight(DataAccessRight):
    async def authorize(self, auth: RequestAuth, service_id: int,
                        operation: DataOperationType, depth: int) -> bool:
        '''
        Authorizes GraphQL API requests by people that are in your network

        :param auth: the object with info about the authentication of the
        client
        :param service_id: service membership that received the GraphQL API
        request
        :returns: whether the client is authorized to perform the requested
        operation
        '''

        _LOGGER.debug('Authorizing network access for data item')

        if self.relations:
            _LOGGER.debug(
               'Relation of network links must be one of '
               f'{", ".join(self.relations)} for member_id {auth.member_id}'
            )
        else:
            _LOGGER.debug('Network links with any relation are acceptable')

        allowed, member = await super().authorize(service_id, operation, depth)
        if allowed is False:
            _LOGGER.debug('Request not authorized')

        if not member:
            _LOGGER.debug(f'This pod is not a member of service {service_id}')
            return False

        network = None
        if auth.member_id:
            network_links = await member.load_network_links()
            _LOGGER.debug(
                f'Found total of {len(network_links or [])} network links'
            )
            network = []
            for link in network_links or []:
                _LOGGER.debug(
                    f'Found link: {", ".join(link["relation"])} to {link["member_id"]}'
                )
                if (link['member_id'] == auth.member_id
                        and (not self.relations
                             or link['relation'].lower() in self.relations)):
                    _LOGGER.debug(
                        f'Link to {link["relation"]} is in {", ".join(self.relations)}'
                    )
                    network.append(link)
                else:
                    _LOGGER.debug(
                        f'Link to {link["relation"]} not in {", ".join(self.relations)}'
                    )

        _LOGGER.debug(f'Found {len(network or [])} applicable network links')

        if len(network or []):
            _LOGGER.debug('Network authorization successful')
            return True

        _LOGGER.debug('Network authorization rejected')
        return False


class ServiceDataAccessRight(DataAccessRight):
    async def authorize(self, auth: RequestAuth, service_id: int,
                        operation: DataOperationType, depth: int) -> bool:
        '''
        Authorizes GraphQL API requests by the service itself

        :param auth: the object with info about the authentication of the
        client
        :param service_id: service membership that received the GraphQL API
        request
        :param operation: the requested operation
        :returns: whether this access right authorizes the requested
        operation. A False return does not mean that the operation is not
        authorized, it just means that this access right does not authorize
        it
        '''

        _LOGGER.debug('Authorizing access by the service for data item')

        allowed, member = await super().authorize(service_id, operation, depth)
        if allowed is False:
            _LOGGER.debug('Request not authorized')

        if not member:
            _LOGGER.debug(f'This pod is not a member of service {service_id}')
            return False

        if service_id == auth.service_id:
            _LOGGER.debug(
                'Authorization success for request from the service: '
                f'{auth.service_id}'
            )
            return True

        _LOGGER.debug(
            'Authorization failed for request from the service: '
            f'{auth.service_id}'
        )
        return False


class AnonymousDataAccessRight(DataAccessRight):
    async def authorize(self, auth: RequestAuth | None, service_id: int,
                        operation: DataOperationType, depth: int) -> bool:
        '''
        Authorizes GraphQL API requests by the service itself

        :param auth: the object with info about the authentication of the
        client
        :param service_id: service membership that received the GraphQL API
        request
        :param operation: the requested operation
        :returns: whether this access right authorizes the requested
        operation. A False return does not mean that the operation is not
        authorized, it just means that this access right does not authorize
        it
        '''

        _LOGGER.debug(
            'Authorizing access by the service for data item {self.name}'
        )

        allowed, member = await super().authorize(service_id, operation, depth)
        if allowed is False:
            _LOGGER.debug('Request not authorized')

        if not member:
            _LOGGER.debug(f'This pod is not a member of service {service_id}')
            return False

        if service_id == auth.service_id:
            _LOGGER.debug(
                'Authorization success for request by an anonymous client to '
                f'service {service_id}'
            )
            return True

        _LOGGER.debug(
            f'Authorization failed for the service: {auth.service_id}'
        )
        return False
