
'''
Test the GraphQL API

Authentication function for GraphQL requests
:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license
'''

import logging

from byoda import config

_LOGGER = logging.getLogger(__name__)

_ACCESS_MARKER = '#accesscontrol'


def authorize_graphql_request(service_id, auth, root, info):
    '''
    Checks the authorization of a graphql request for a service.
    It is called by the code generated from the Jinja
    templates implementing GraphQL support
    '''

    # Authorization is declined unless we find it is allowed
    access_allowed = False

    # We need to review whether the requestor is authorized to access
    # the data in the request
    schema = config.server.account.memberships[service_id].schema

    # This is the start of the data definition of the JsonSchema
    schema_data = schema.schema_data['schema']['properties']

    json_key = info.path[0]

    # This provides the type of operation requested: Query, Mutate, Subscribe
    operation = info.operation.operation

    if json_key in schema_data and _ACCESS_MARKER in schema_data[json_key]:
        for accesscontrol in schema_data[json_key][_ACCESS_MARKER]:
            for entity, access in accesscontrol.items():
                if not authorize_operation(operation, access):
                    continue

                if entity == 'member':
                    if authorize_member(service_id, auth):
                        return True

    return access_allowed


def authorize_operation(operation, access):
    if operation == 'query' and 'read' in access:
        return True
    if operation == 'subscribe' and 'read' in access:
        return True
    if operation == 'mutate' and 'update' in access and 'delete' in access:
        return True


def authorize_member(service_id, auth):
    local_member_id = config.server.account.memberships[service_id].member_id
    if auth.member_id and auth.member_id == local_member_id:
        return True

    return False
