#!/usr/bin/python3

import asyncio
from typing import AsyncGenerator

import strawberry
from fastapi import FastAPI
from strawberry.asgi import GraphQL


@strawberry.type
class Query:
    @strawberry.field
    def hello(self) -> str:
        return "world"


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def count(self, target: int = 3) -> AsyncGenerator[int, None]:
        for i in range(target):
            yield i
            await asyncio.sleep(0.5)


schema = strawberry.Schema(query=Query, subscription=Subscription)


graphql_app = GraphQL(schema)

app = FastAPI()
app.add_route("/graphql", graphql_app)
app.add_websocket_route("/graphql", graphql_app)
