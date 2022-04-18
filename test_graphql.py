#!/usr/bin/env python3

from __future__ import annotations

import typing

import strawberry
from strawberry.schema.config import StrawberryConfig
from strawberry.types import Info


def network_link_timestamp(root: network_link, info: Info) -> str:
    return info.context['data']['timestamp']


def network_link_member_id(root: network_link, info: Info) -> str:
    return info.context['data']['member_id']


def network_link_relation(root: network_link, info: Info) -> str:
    return info.context['data']['relation']


@strawberry.type
class network_link:
    timestamp_value: str
    member_id_value: str
    relation_value: str

    timestamp: str = strawberry.field(resolver=network_link_timestamp)
    member_id: str = strawberry.field(resolver=network_link_member_id)
    relation: str = strawberry.field(resolver=network_link_relation)


links_dict = [
    {'timestamp': '1', 'member_id': 'a', 'relation': 'friend'},
    {'timestamp': '2', 'member_id': 'b', 'relation': 'son'},
    {'timestamp': '3', 'member_id': 'c', 'relation': 'colleague'},
]


def network_links(info) -> typing.List[network_link]:
    ret_data = []
    for obj in links_dict:
        info.context['data'] = obj
        network_link_data = network_link(
            obj['timestamp'],
            obj['member_id'],
            obj['relation']
        )
        ret_data.append(network_link_data)
    return ret_data


@strawberry.type
class Query:
    network_links: typing.List[network_link] = strawberry.field(
        resolver=network_links
    )


schema = strawberry.Schema(
    query=Query,
    config=StrawberryConfig(auto_camel_case=False)
)
