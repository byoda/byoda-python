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
    books: typing.List[Book]
    authors: typing.List[Author]


@strawberry.type
class Mutation:
    @strawberry.field
    def addBook(self, title: str, author: str) -> Book:
        print(f'Adding {title} by {author}')

        return Book(title=title, author=author)


schema = strawberry.Schema(query=Query, mutation=Mutation)
