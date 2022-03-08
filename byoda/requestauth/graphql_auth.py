
'''
Test the GraphQL API

Authentication function for GraphQL requests
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import logging
from enum import Enum

from fastapi import HTTPException

from byoda.datatypes import IdType

from byoda.datamodel.member import Member

from byoda.requestauth import RequestAuth

from byoda import config

_LOGGER = logging.getLogger(__name__)

_ACCESS_MARKER = '#accesscontrol'


class DataOperationType(Enum):
    # flake8: noqa=E221
    CREATE      = 'create'
    READ        = 'read'
    UPDATE      = 'update'
    APPEND      = 'append'
    SEARCH      = 'search'
    # Mutate can be either create, update, append or delete
    MUTATE      = 'mutate'


def authorize_graphql_request(service_id: int, info, root):
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
        raise HTTPException(status_code=400, detail='Authentication failure')

    # This is the start of the data definition of the JsonSchema
    json_schema = member.schema.json_schema['jsonschema']['properties']

    # This provides the type of operation requested: Query, Mutate, Subscribe
    operation = info.operation.operation

    json_key = info.path[1]
    data_operation = DataOperationType.READ
    if operation.value == 'mutation':
        # strip of the 'mutate_' prefix
        json_key = json_key[len('mutate_'):]
        data_operation = DataOperationType.UPDATE

    if json_key in json_schema and _ACCESS_MARKER in json_schema[json_key]:
        access_controls = json_schema[json_key][_ACCESS_MARKER]
        result = authorize_request(data_operation, access_controls, info.context['auth'], service_id)
        if result is True:
            return result

    return access_allowed


def authorize_request(operation: DataOperationType,
                      access_controls: dict,
                      auth: RequestAuth,
                      service_id: int) -> bool:
    '''
    Check whether the client is allowed to perform the operation by the
    access controls

    :param operation: the request operation
    :param access_controls: the dict with '#accesscontrol from the service
    contract
    :param auth: the identify of the client
    '''

    for entity, permissions in access_controls.items():
        # Check if the GraphQL operation is allowed per the permissions
        if operation.value not in permissions:
            return

        # Now check whether the requestor matches the entity of the
        # access control
        if entity == 'member' and auth.id_type == IdType.MEMBER:
            if authorize_member(service_id, auth):
                return True


def authorize_graphql_query(service_id, info, root):
    '''
    Checks the authorization of a graphql request for a service.

    It is called by the code generated from the Jinja templates implementing
    GraphQL support
    '''

    # Authorization is declined unless we find it is allowed
    access_allowed = False

    # We need to review whether the requestor is authorized to access
    # the data in the request
    member = config.server.account.memberships[service_id]

    # This is the start of the data definition of the JsonSchema
    json_sub_schema = member.schema.json_schema['jsonschema']['properties']

    # We walk the path through the data model. If we don't find explicit
    # permission at some level than we reject the request by default.
    for obj in reversed(info.path):
        if obj in json_sub_schema and _ACCESS_MARKER in json_sub_schema[obj]:
            access_control = json_sub_schema[obj][_ACCESS_MARKER]
            for entity, permissions in access_control.items():
                # Check if the GraphQL operation is allowed per the permissions
                if 'read' not in permissions:
                    continue

                # Now check whether the requestor matches the entity of the
                # access control
                auth: RequestAuth = info.context['auth']
                if entity == 'member' and auth.id_type == IdType.MEMBER:
                    if authorize_member(service_id, info.context['auth']):
                        access_allowed = True

        # Check the access at the next-deeper level of the data model in
        # the next iteration
        if 'properties' in json_sub_schema[obj]:
            json_sub_schema = json_sub_schema[obj]['properties']
        else:
            return access_allowed

    return access_allowed


def authorize_graphql_mutation(service_id, auth, root, info):
    '''
    Checks the authorization of a graphql request for a service.
    It is called by the code generated from the Jinja
    templates implementing GraphQL support
    '''

    raise NotImplementedError
    # Authorization is declined unless we find it is allowed
    access_allowed = False

    # We need to review whether the requestor is authorized to access
    # the data in the request
    member = config.server.account.memberships[service_id]

    # This is the start of the data definition of the JsonSchema
    json_schema = member.schema.json_schema['jsonschema']['properties']

    json_key = info.path[1]

    # This provides the type of operation requested: Query, Mutate, Subscribe
    operation = info.operation.operation

    json_key = info.path[1]
    if operation.value == 'mutation':
        # strip of the 'mutate_' prefix
        json_key = json_key[len('mutate_'):]

    if json_key in json_schema and _ACCESS_MARKER in json_schema[json_key]:
        access_control = json_schema[json_key][_ACCESS_MARKER]
        for entity, permissions in access_control.items():
            # Check if the GraphQL operation is allowed per the permissions
            if not authorize_operation(operation, permissions):
                continue

            # Now check whether the requestor matches the entity of the
            # access control
            auth: RequestAuth = info.context['auth']
            if entity == 'member' and auth.id_type == IdType.MEMBER:
                if authorize_member(service_id, info.context['auth']):
                    return True

    return access_allowed


def authorize_graphql_append(service_id, auth, root, info):
    '''
    Checks the authorization of a graphql request for a service.
    It is called by the code generated from the Jinja
    templates implementing GraphQL support
    '''

    raise NotImplementedError
    # Authorization is declined unless we find it is allowed
    access_allowed = False

    # We need to review whether the requestor is authorized to access
    # the data in the request
    member = config.server.account.memberships[service_id]

    # This is the start of the data definition of the JsonSchema
    json_schema = member.schema.json_schema['jsonschema']['properties']

    json_key = info.path[1]

    # This provides the type of operation requested: Query, Mutate, Subscribe
    operation = info.operation.operation

    json_key = info.path[1]
    if operation.value == 'mutation':
        # strip of the 'mutate_' prefix
        json_key = json_key[len('mutate_'):]

    if json_key in json_schema and _ACCESS_MARKER in json_schema[json_key]:
        access_control = json_schema[json_key][_ACCESS_MARKER]
        for entity, permissions in access_control.items():
            # Check if the GraphQL operation is allowed per the permissions
            if not authorize_operation(operation, permissions):
                continue

            # Now check whether the requestor matches the entity of the
            # access control
            auth: RequestAuth = info.context['auth']
            if entity == 'member' and auth.id_type == IdType.MEMBER:
                if authorize_member(service_id, info.context['auth']):
                    return True

    return access_allowed


def authorize_operation(operation, access):
    if operation.value == 'query' and 'read' in access:
        return True
    if operation.value == 'subscribe' and 'read' in access:
        return True
    if operation.value == 'mutation' and (
            'update' in access and 'delete' in access):
        return True


def authorize_member(service_id, auth):
    member = config.server.account.memberships.get(service_id)

    if auth.member_id and member and auth.member_id == member.member_id:
        return True

    return False
