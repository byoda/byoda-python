#!/usr/bin/env python3.9

from __future__ import annotations

import strawberry
from strawberry.schema.config import StrawberryConfig
from strawberry.types import Info


def first_name_func(root: User, info: Info) -> str:
    return f"Some {info.field_name}"


def last_name_func(root: User, info: Info) -> str:
    return f"Test {info.field_name}"


@strawberry.type
class User:
    first_name: str = strawberry.field(resolver=first_name_func)
    last_name: str = strawberry.field(resolver=last_name_func)


@strawberry.type
class Query:
    @strawberry.field
    def last_user(self) -> User:
        return User()


schema = strawberry.Schema(
    query=Query,
    config=StrawberryConfig()
)
