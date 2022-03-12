
'''
Test the GraphQL API

Authentication function for GraphQL requests
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import logging
from enum import Enum
from typing import Optional

from strawberry.types import Info

from fastapi import HTTPException

from byoda.datatypes import IdType
from byoda.datatypes import DataOperationType

from byoda.datamodel.member import Member

from byoda.requestauth import RequestAuth

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


def authorize_graphql_request(operation: DataOperationType, service_id: int,
                              info: Info, root = None):
    '''
    Checks the authorization of a graphql request for a service.
    It is called by the code generated from the Jinja
    templates implementing GraphQL support
    '''

    # Authorization is declined unless we find it is allowed
    access_allowed = False

    # We need to review whether the requestor is authorized to access
    # the data in the request
    member: Member = config.server.account.memberships.get(service_id)
    if not member:
        raise HTTPException(
            status_code=404, detail=f'Service {service_id} not found'
        )

    # This is the start of the data definition of the JsonSchema
    json_sub_schema = member.schema.json_schema['jsonschema']['properties']

    # We walk the path through the data model. If we don't find explicit
    # permission at some level than we reject the request by default.
    for obj in reversed(info.path):
        if obj is None or obj.lower() == 'mutation':
            continue
        elif obj.startswith('mutate_'):
            key = obj[len('mutate_'):]
        else:
            key = obj

        if key in json_sub_schema and _ACCESS_MARKER in json_sub_schema[key]:
            access_controls = json_sub_schema[key][_ACCESS_MARKER]
            result = authorize_request(
                operation, access_controls, info.context['auth'],
                service_id
            )
            if result is True:
                return result

        # Check the access at the next-deeper level of the data model in
        # the next iteration
        if 'properties' in json_sub_schema[key]:
            json_sub_schema = json_sub_schema[key]['properties']
        else:
            return access_allowed

    return access_allowed


def authorize_request(operation: DataOperationType, access_controls: dict,
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
        None if the access controls are not applicable to the client
    '''

    for entity, access_control in access_controls.items():
        # Check if the GraphQL operation is allowed per the permissions
        # before matching the entity for the controls with the caller
        permitted_actions = access_control['permissions']
        if operation.value not in permitted_actions:
            return

        # Now check whether the requestor matches the entity of the
        # access control

        # Anyone is allowed to
        if entity == AccessEntityType.ANONYMOUS.value:
            if operation.value in permitted_actions:
                return True

        # Are we performing the GraphQL API ourselves?
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

        if entity == AccessEntityType.NETWORK.value:
            distance = access_control.get('distance', 1)
            if distance < 1:
                raise ValueError('Network distance must be larger than 0')
            raise NotImplementedError


def authorize_member(service_id: int, auth: RequestAuth) -> bool:
    member = config.server.account.memberships.get(service_id)

    if auth.member_id and member and auth.member_id == member.member_id:
        return True

    return False


def authorize_service(service_id: int, auth: RequestAuth) -> bool:
    member = config.server.account.memberships.get(service_id)

    if (member and auth.service_id is not None
            and auth.service_id == service_id):
        return True

    return False


def authorize_network(service_id: int, auth: RequestAuth, distance: int) -> bool:
    if distance > 1:
        raise NotImplementedError(
            f'Network distance of 1 is only supported value: {distance}'
        )

    member = config.server.account.memberships.get(service_id)

    if member and auth.member_id:
        raise NotImplementedError('See if the member is in our network for the service')
        return True

    return False