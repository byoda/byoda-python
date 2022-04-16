#!/usr/bin/env python3

from __future__ import annotations

import typing

import strawberry
from strawberry.schema.config import StrawberryConfig
from strawberry.types import Info

from byoda.requestauth import RequestAuth as RequestAuthByoda
from byoda.requestauth.graphql_authorization import DataOperationType as DataOperationType_Byoda
from byoda.requestauth.graphql_authorization import authorize_graphql_request as authorize_graphql_request_Byoda

from fastapi import HTTPException

from byoda.datamodel.member import Member as MemberClassByoda


import logging as loggingByoda


_LOGGER = loggingByoda.getLogger(__name__)


def authenticate(root, info, data_operation: DataOperationType_Byoda):
    '''
    This is middleware called by the code generated from the Jinja
    templates implementing GraphQL support
    '''

    if not info.context or not info.context['request']:
        raise HTTPException(
            status_code=403, detail='No authentication provided'
        )

    try:
        # Checks that a client cert was provided and that the cert and
        # certchain is correct
        auth = RequestAuthByoda.authenticate_graphql_request(
            info.context['request'], 4294929430
        )
        info.context['auth'] = auth
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail='Authentication failed'
        )

    if not auth.is_authenticated:
        raise HTTPException(
            status_code=403, detail='No authentication provided'
        )

    try:
        # Check whether the authenticated client is authorized to request
        # the data
        return authorize_graphql_request_Byoda(
            data_operation, 4294929430, info
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail='Not authorized')


@strawberry.type
class network_link:
    timestamp: int
    member_id: str
    relation: str

    @strawberry.field
    def timestamp(self, info: Info) -> str:
        return info.context['data']['timestamp']

    @strawberry.field
    def member_id(self, info: Info) -> str:
        return info.context['data']['member_id']

    @strawberry.field
    def relation(self, info: Info) -> str:
        return info.context['data']['relation']


@strawberry.input
class network_linkInput:
    @strawberry.field
    def timestamp(self, info: Info) -> str:
        # return info.context['data']['timestamp']
        return self.timestamp

    @strawberry.field
    def member_id(self, info: Info) -> str:
        # return info.context['data']['member_id']
        return self.member_id

    @strawberry.field
    def relation(self, info: Info) -> str:
        # return info.context['data']['relation']
        return self.relation


links = [
    network_link(timestamp='1', member_id='a', relation='friend'),
    network_link(timestamp='2', member_id='b', relation='son'),
    network_link(timestamp='3', member_id='c', relation='colleague'),
]

links_dict = [
    {'timestamp': '1', 'member_id': 'a', 'relation': 'friend'},
    {'timestamp': '2', 'member_id': 'b', 'relation': 'son'},
    {'timestamp': '3', 'member_id': 'c', 'relation': 'colleague'},
]

@strawberry.type
class Query:
    @strawberry.field
    def network_links(self, info) -> typing.List[network_link]:
        _LOGGER.debug('Resolving network_links')

        #result = authenticate(self, info, DataOperationType_Byoda.READ)
        #if not result:
        #    raise HTTPException(status_code=400, detail='Authentication failed')

        #data = MemberClassByoda.get_data(4294929430, info)
        data = links_dict
        ret_data = []
        for obj in data or []:
            info.context['data'] = obj
            # BUG: class instantiation does not return a usable value
            network_link_data = network_link(
                timestamp=obj['timestamp'],
                member_id=obj['member_id'],
                relation=obj['relation'],
            )
            ret_data.append(network_link_data)

        return ret_data


schema = strawberry.Schema(
    query=Query,
    config=StrawberryConfig(auto_camel_case=False)
)
