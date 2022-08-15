'''
Class for modeling permissions specified in the JSON Schema used
for generating the GraphQL Strawberry code based on Jinja2
templates

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from typing import TypeVar

from byoda.datatypes import RightsEntityType
from byoda.datatypes import DataOperationType

from byoda.datamodel.member import Member

from byoda import config

_LOGGER = logging.getLogger(__name__)

RequestAuth = TypeVar('RequestAuth')


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
            self.data_operation_type: DataOperationType = \
                DataOperationType(permission_data)
            return

        self.data_operation_type: DataOperationType = \
            DataOperationType(permission_data['permission'])

        self.distance = permission_data.get('distance', 0)

        # Relations are converted to lower case
        relations = permission_data.get('relation')
        if isinstance(relations, str):
            self.relations = set(relations.lower())
        else:
            self.relations = [
                relation.lower() for relation in relations
            ]

        self.source_signature_required = \
            permission_data.get('source_signature_required')
        self.anonimized_responses = permission_data.get('anonimized_responses')

        if self.data_operation_type == DataOperationType.SEARCH:
            if (self.distance or self.relations or
                    self.source_signature_required or
                    self.anonimized_responses):
                raise ValueError('Search right cannot have other '
                                 'parameters than the permission')
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
            if entity_type == RightsEntityType.NETWORK:
                permission = NetworkDataAccessRight(action)

            permissions.append(permission)

        return permissions


class MemberDataAccessRight(DataAccessRight):
    async def authorize(self, auth: RequestAuth, service_id: int) -> bool:
        '''
        Authorizes GraphQL API requests by ourselves

        :param auth: the object with info about the authentication of the
        client
        :param service_id: service membership that received the GraphQL API
        request
        :returns: whether the client is authorized to perform the requested
        operation
        '''

        _LOGGER.debug('Authorizing network access for data item {self.name}')

        member = config.server.account.memberships.get(service_id)
        if not member:
            _LOGGER.debug(f'No membership found for service {service_id}')
            return False

        if auth.member_id and auth.member_id == member.member_id:
            _LOGGER.debug(
                f'Authorization success for ourselves: {auth.member_id}'
            )
            return True

        _LOGGER.debug(f'Authorization failed for ourselves: {auth.member_id}')
        return False


class NetworkDataAccessRight(DataAccessRight):
    async def authorize(self, auth: RequestAuth, service_id: int) -> bool:
        '''
        Authorizes GraphQL API requests by people that are in your network

        :param auth: the object with info about the authentication of the
        client
        :param service_id: service membership that received the GraphQL API
        request
        :returns: whether the client is authorized to perform the requested
        operation
        '''

        _LOGGER.debug('Authorizing network access for data item {self.name}'
                      )
        if self.relations:
            _LOGGER.debug(
               'Relation of network links must be one of '
               f'{",".join(self.relations)}'
            )
        else:
            _LOGGER.debug('Network links with any relation are acceptable')

        member: Member = config.server.account.memberships.get(service_id)
        if not member:
            _LOGGER.debug(f'No membership found for service {service_id}')
            return False

        if auth.member_id:
            await member.load_data()
            network_links = member.data.get('network_links') or []
            _LOGGER.debug(f'Found total of {len(network_links)} network links')
            network = [
                link for link in network_links
                if (link['member_id'] == auth.member_id
                    and (not self.relations or
                    link['relation'].lower() in self.relations))
            ]
        _LOGGER.debug(f'Found {len(network)} applicable network links')

        if len(network):
            _LOGGER.debug('Network authorization successful')
            return True

        _LOGGER.debug('Network authorization rejected')
        return False
