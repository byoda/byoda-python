
'''
Test the GraphQL API

Authentication function for GraphQL requests
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import re
import logging
from typing import List, TypeVar

from strawberry.types import Info

from fastapi import HTTPException

from byoda.datatypes import IdType
from byoda.datatypes import DataOperationType

from byoda.datamodel.member import Member
from byoda.requestauth.requestauth import RequestAuth

from byoda import config

_LOGGER = logging.getLogger(__name__)

_ACCESS_MARKER = '#accesscontrol'

SchemaDataItem = TypeVar('SchemaDataItem')


async def authorize_graphql_request(operation: DataOperationType,
                                    service_id: int, info: Info, depth: int,
                                    root=None):
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
        raise HTTPException(status_code=401, detail='Access denied')

    # data_classes contain the access permissions for the class
    data_classes = member.schema.data_classes

    key = get_query_key(info.path)

    if key not in data_classes:
        raise ValueError(
            f'Request for data element {key} that is not included at the '
            'root level of the service contract'
        )

    _LOGGER.debug(f'Authorizing request for data element {key}')

    auth: RequestAuth = info.context['auth']

    if depth and member.member_id != auth.member_id:
        _LOGGER.debug(
            'Attempt to perform recursive request by someone else '
            f'than the owner of the pod: {auth.member_id}'
        )
        raise ValueError('Only owner of pod can submit recursive queries')

    data_class: SchemaDataItem = data_classes[key]
    access_allowed = await data_class.authorize_access(
        operation, auth, service_id
    )

    if access_allowed is None:
        # If no access controls were defined at all in the schema (which
        # should never be the case) then only the pod membership has access
        if (auth.id_type == IdType.MEMBER
                and auth.member_id == member.member_id and
                operation == DataOperationType.READ):
            access_allowed = True
        else:
            access_allowed = False

    return access_allowed


def get_query_key(path: List[str]) -> str:
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
        elif obj.endswith('_connection'):
            key = obj[:-1 * len('_connection')]
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

    # BUG: Strawberry applies camel casing eventhough we tell it not to when
    # setting up the graphql API in graphql_schema.jinja
    key = re.sub('([A-Z]{1})', r'_\1', key).lower()

    return key
