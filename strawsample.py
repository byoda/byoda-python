from __future__ import annotations

import strawberry
from strawberry.types import Info

@strawberry.type
class Person:
    @strawberry.field
    def givenName(self, info: Info) -> str:
        return info.context['data'].get('givenName')

    @strawberry.field
    def familyName(self, info: Info) -> str:
        return info.context['data'].get('familyName')


@strawberry.type
class Query:
    @strawberry.field
    def person(self, info: Info) -> Person:
        info.context['data'] = {
            'givenName': 'Peter',
            'familyName': 'Bob'

        }
        return Person()


@strawberry.type
class Mutation:
    @strawberry.field
    def mutatePerson(self, info: Info, givenName: str, familyName: str) -> Person:
        print(f'Adding {givenName} {familyName}')
        info.context['data'] = {
            'givenName': 'Peter',
            'familyName': 'Bob'

        }
        return Person()


schema = strawberry.Schema(query=Query, mutation=Mutation)
