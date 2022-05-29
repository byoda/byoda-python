
'''
Test the GraphQL API

Authentication function for GraphQL requests
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import re
import logging
from enum import Enum
from typing import Optional, List, Tuple, Dict

from strawberry.types import Info

from fastapi import HTTPException

from byoda.datatypes import IdType
from byoda.datatypes import DataOperationType

from byoda.datamodel.member import Member

from byoda.requestauth.requestauth import RequestAuth

from byoda import config

_LOGGER = logging.getLogger(__name__)

_ACCESS_MARKER = '#accesscontrol'


class AccessEntityType(Enum):
    # flake8: noqa=E221
    MEMBER      = 'member'
    NETWORK     = 'network'
    SERVICE     = 'service'
    ANYMEMBER   = 'anymember'
    ANONYMOUS   = 'anonymous'


async def authorize_graphql_request(operation: DataOperationType, service_id: int,
                              info: Info, root = None):
    '''
    Checks the authorization of a graphql request for a service.
    It is called by the code generated from the Jinja
    templates implementing GraphQL support
    '''

    _LOGGER.debug(
        f'Authorizing GraphQL request for operation {operation.value} for '
        f'service {service_id} with action {info.path.typename} for key '
        f'{info.path.key}'
    )

    # We need to review whether the requestor is authorized to access
    # the data in the request
    member: Member = config.server.account.memberships.get(service_id)

    if not member:
        # We do not want to expose whether the account is a member of
        # a service. Such requests should not happen as requests must
        # be sent to the membership-FQDN but this is an additional safeguard
        raise HTTPException(
            status_code=401, detail=f'Access denied'
        )

    # This is the start of the data definition of the JsonSchema
    data_schema = member.schema.json_schema['jsonschema']['properties']

    key = _get_query_key(info.path)

    if key not in data_schema:
        raise ValueError(
            f'Request for data element {key} that is not included at the root level of '
            'the service contract'
        )

    _LOGGER.debug(f'Authorizing request for data element {key}')

    auth: RequestAuth = info.context['auth']
    access_allowed = await _check_data_access(
        key, data_schema[key], operation, auth, service_id
    )

    if access_allowed is None:
        # If no access controls were defined at all in the schema (which should never
        # be the case) then only the pod membership has access
        if (auth.id_type == IdType.MEMBER and auth.member_id == member.member_id and
            operation == DataOperationType.READ):
            access_allowed = True
        else:
            access_allowed = False

    return access_allowed

async def _check_data_access(data_element: str, subschema: Dict,
                       operation: DataOperationType, auth: RequestAuth,
                       service_id: int) -> Optional[bool]:
    '''
    Recursive function to validate whether the access to the data
    requested in the GraphQL query is permitted according to the
    service contract

    :param data_element: the name of the data element for which the subschema
    is provided
    :param subschema: the section of the serivce contract for this data element
    :param operation: the type of access request
    :param auth: the information about the authentication of the request
    :param service_id: the service for which the access is requested
    :returns: whether the data access request is allowed by the service
    contract
    '''

    access_controls = subschema.get(_ACCESS_MARKER)
    if access_controls:
        _LOGGER.debug(
            f'Data element {data_element} has access controls defined'
        )

        access_allowed = await authorize_operation(
            operation, access_controls, auth, service_id
        )
        _LOGGER.debug(
            f'Is Access granted for data element {data_element}: '
            f'{access_allowed}'
        )

        # If permission is denied, we do not need to check access to
        # child elements as if access permissions are defined but do not
        # cover the request then access to child elements is not permitted
        # either
        if access_allowed is False:
            return access_allowed

        # Check the access at the next-deeper level of the data model in
        # the next level of recursion
        child_subschema = subschema.get('properties')
        if child_subschema:
            _LOGGER.debug(
                f'Data element {data_element} has {len(child_subschema.keys())}'
                ' child elements'
            )
            for child_data_element, child_element_schema in child_subschema.items():
                child_access_allowed = await _check_data_access(
                    child_data_element, child_element_schema, operation, auth,
                    service_id
                )
                # child_result could be True or None but that does not impact
                # whether the request is allowable at the higher-level data
                # element
                if child_access_allowed is False:
                    return False

        return access_allowed

def _get_query_key(path: List[str]) -> str:
    '''
    Gets the name of the data element from the service contract that is
    requested in the GraphQL query.
    '''
    # The GraphQL Jinja2 template prefixes
    # data elements with 'mutate_' for dicts and 'append_' for arrays for
    # GraphQL Mutate queries
    key = None
    for obj in reversed(path):
        if obj is None or obj.lower() in ('query', 'mutation'):
            continue
        elif obj.startswith('mutate_'):
            key = obj[len('mutate_'):]
            break
        elif obj.startswith('append_'):
            key = obj[len('append_'):]
            break
        elif obj.startswith('update_'):
            key = obj[len('update_'):]
            break
        elif obj.startswith('delete_from_'):
            key = obj[len('delete_from_'):]
            break
        else:
            key = obj
            break

    if not key:
        raise ValueError(
            'No valid key to the data element was provided in GraphQL query'
        )

    # BUG: Strawberry applies camel casing eventhough we tell it not to when setting
    # up the graphql API in graphql_schema.jinja
    key = re.sub('([A-Z]{1})', r'_\1', key).lower()

    return key

async def authorize_operation(operation: DataOperationType, access_controls: dict,
                      auth: RequestAuth, service_id: int) -> Optional[bool]:
    '''
    Check whether the client is allowed to perform the operation by the
    access controls

    :param operation: the requested operation
    :param access_controls: dict with '#accesscontrol from the service contract
    :param auth: the result of the authentication of the request by the client
    :returns:
        True if the access_controls permit the client to execute the operation
        False if the access_controls deny the client to execute the operation
        None if the access controls are not applicable to the client ID or type
    '''

    for entity, access_control in access_controls.items():
        # Check if the GraphQL operation is allowed per the permissions
        # before matching the entity for the controls with the caller
        permitted_actions = access_control['permissions']
        if operation.value not in permitted_actions:
            continue

        # Now check whether the requestor matches the entity of the
        # access control

        # Anyone is allowed to
        if entity == AccessEntityType.ANONYMOUS.value:
            if operation.value in permitted_actions:
                return True

        # Are we querying the GraphQL API ourselves?
        if entity == AccessEntityType.MEMBER.value:
            if auth.id_type == IdType.MEMBER:
                if authorize_member(service_id, auth):
                    if operation.value in permitted_actions:
                        return True

        # Did the service server call our GraphQL API?
        if entity == AccessEntityType.SERVICE.value:
            if auth.id_type == IdType.SERVICE:
                if authorize_service(service_id, auth):
                    if operation.value in permitted_actions:
                        return True

        if entity == AccessEntityType.ANYMEMBER.value:
            if auth.id_type == IdType.MEMBER:
                if authorize_any_member(service_id, auth):
                    if operation.value in permitted_actions:
                        return True

        if entity == AccessEntityType.NETWORK.value:
            distance = access_control.get('distance', 1)
            if distance < 1:
                raise ValueError('Network distance must be larger than 0')

            relation = access_control.get('relation')
            if await authorize_network(service_id, auth, distance, relation):
                if operation.value in permitted_actions:
                    return True


def authorize_member(service_id: int, auth: RequestAuth) -> bool:
    '''
    Authorize ourselves

    :param service_id: service membership that received the GraphQL API request
    :param auth: the object with info about the authentication of the client
    :returns: whether the client is authorized to perform the requested
    operation
    '''
    member = config.server.account.memberships.get(service_id)

    if auth.member_id and member and auth.member_id == member.member_id:
        return True

    return False


def authorize_any_member(service_id: int, auth: RequestAuth) -> bool:
    '''
    Authorizes any member of the service, regardless of whether the client
    is in our network

    :param service_id: service membership that received the GraphQL API request
    :param auth: the object with info about the authentication of the client
    :returns: whether the client is authorized to perform the requested
    operation
    '''

    member = config.server.account.memberships.get(service_id)

    if member and auth.member_id and auth.service_id == service_id:
        return True

    return False


def authorize_service(service_id: int, auth: RequestAuth) -> bool:
    '''
    Authorizes requests made with the TLS cert of the service

    :param service_id: service membership that received the GraphQL API request
    :param auth: the object with info about the authentication of the client
    :returns: whether the client is authorized to perform the requested
    operation
    '''

    member = config.server.account.memberships.get(service_id)

    if (member and auth.service_id is not None
            and auth.service_id == service_id):
        return True

    return False


async def authorize_network(service_id: int, auth: RequestAuth, distance: int,
                            relation: str) -> bool:
    '''
    Authorizes GraphQL API requests by people that are in your network

    :param service_id: service membership that received the GraphQL API request
    :param auth: the object with info about the authentication of the client
    :param distance: max distance from the owner of the pod to the person
    submitting the GraphQL request. Currently, only direct links (distance=1)
    are supported
    :param relation: only consider network links with the specified relation.
    If relation is 'None' then all network links are considered
    :returns: whether the client is authorized to perform the requested
    operation
    '''

    if distance > 1:
        raise ValueError(
            f'Network distance of 1 is only supported value: {distance}'
        )

    if not isinstance(relation, list):
        relation = list(relation)

    member: Member = config.server.account.memberships.get(service_id)

    if member and auth.member_id:
        await member.load_data()
        network_links = member.data.get('network_links')
        network = [
            link for link in network_links
            if link['member_id'] == str(auth.member_id)
                 and (not relation or
                    link['relation'].lower() in relation
                 )
        ]
        if len(network):
            return True

    return False