#!/usr/bin/env python3

# flake8: noqa=E501

from __future__ import annotations

import strawberry
from strawberry.types import Info

from byoda.datamodel import Member as MemberClassByoda

import logging as loggingByoda

# from byoda.datamodel import Member as MemberClassByoda

from byoda.requestauth import RequestAuth as RequestAuthByoda
from byoda.requestauth import authorize_graphql_request as authorize_graphql_request_Byoda


_LOGGER = loggingByoda.getLogger(__name__)


@strawberry.type
class Person:
    @strawberry.field
    def givenName(self, info: Info) -> str:
        return info.context['data']['givenName']

    @strawberry.field
    def additionalNames(self, info: Info) -> str:
        return info.context['data']['additionalNames']

    @strawberry.field
    def familyName(self, info: Info) -> str:
        return info.context['data']['familyName']

    @strawberry.field
    def email(self, info: Info) -> str:
        return info.context['data']['email']

    @strawberry.field
    def avatarUrl(self, info: Info) -> str:
        return info.context['data']['avatarUrl']

    @strawberry.field
    def homepageUrl(self, info: Info) -> str:
        return info.context['data']['homepageUrl']

@strawberry.type
class Query:
    @staticmethod
    def authenticate(root, info):
        '''
        This is middleware called by the code generated from the Jinja
        templates implementing GraphQL support
        '''

        if not info.context or not info.context['request']:
            raise ValueError('No info to authenticate client')

        try:
            # Checks that a client cert was provided and that the cert and
            # certchain is correct
            auth = RequestAuthByoda.authenticate_request(info.context['request'])
            if not auth.is_authenticated:
                raise ValueError('Client is not authentication')
        except Exception as exc:
            raise ValueError(f'Authentication failed: {exc}')

        try:
            # Check whether the authenticated client is authorized to request
            # the data
            authorize_graphql_request_Byoda(0, auth, root, info)
        except Exception as exc:
            raise ValueError(f'Authorization failed: {exc}')

    @strawberry.field
    def person(self, info: Info) -> Person:
        _LOGGER.debug('Resolving person')
        Query.authenticate(self, info)
        info.context['data'] = {
            'givenName': 'Peter',
            'additionalNames': '',
            'familyName': 'Johnson',
            'email': 'peter@byoda.org',
            'avatarUrl': 'https://avatar.url/',
            'homepageUrl': 'https://www.byoda.org',
        }
        # info.context['data'] = MemberClassByoda.get_data(0, info.path)
        person = Person()
        return person

@strawberry.type
class Mutation:
    @staticmethod
    def authenticate(root, info):
        '''
        This is middleware called by the code generated from the Jinja
        templates implementing GraphQL support
        '''

        if not info.context or not info.context['request']:
            raise ValueError('No info to authenticate client')

        try:
            # Checks that a client cert was provided and that the cert and
            # certchain is correct
            auth = RequestAuthByoda.authenticate_request(info.context['request'])
            if not auth.is_authenticated:
                raise ValueError('Client is not authentication')
        except Exception as exc:
            raise ValueError(f'Authentication failed: {exc}')

        try:
            # Check whether the authenticated client is authorized to request
            # the data
            authorize_graphql_request_Byoda(0, auth, root, info)
        except Exception as exc:
            raise ValueError(f'Authorization failed: {exc}')

    @strawberry.mutation
    def mutatePerson(self, info: Info,
               givenName: str = None,
               additionalNames: str = None,
               familyName: str = None,
               email: str = None,
               avatarUrl: str = None,
               homepageUrl: str = None,
            ) -> Person:
        _LOGGER.debug('blah')
        Query.authenticate(self, info)
        info.context['data'] = {
            'givenName': 'Peter',
            'additionalNames': '',
            'familyName': 'Johnson',
            'email': 'peter@byoda.org',
            'avatarUrl': 'https://avatar.url/',
            'homepageUrl': 'https://www.byoda.org',
        }
        return Person


schema = strawberry.Schema(query=Query, mutation=Mutation)
