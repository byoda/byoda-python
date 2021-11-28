from __future__ import annotations

import typing
import strawberry


@strawberry.type
class Book:
    title: str
    author: Author


@strawberry.type
class Author:
    name: str
    books: typing.List['Book']


@strawberry.type
class Query:
    @strawberry.field
    def hello() -> str:
        return "world"


@strawberry.type
class Mutation:
    @strawberry.mutation
    def add_book(self, title: str, author: str) -> Book:
        print(f'Adding {title} by {author}')

        return Book(title=title, author=author)


schema = strawberry.Schema(query=Query, mutation=Mutation)
