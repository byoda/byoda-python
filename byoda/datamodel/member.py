'''
Class for modeling an account on a network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from uuid import uuid4
from copy import copy
from typing import List, Dict, TypeVar, Callable

from graphene import Mutation as GrapheneMutation
from byoda.datatypes import CsrSource

from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema
from byoda.datamodel.memberdata import MemberData

from byoda.datastore.document_store import DocumentStore

from byoda.util.secrets import MemberSecret, MemberDataSecret
from byoda.util.secrets import Secret, MembersCaSecret

from byoda import config


_LOGGER = logging.getLogger(__name__)

Account = TypeVar('Account', bound='Account')
Network = TypeVar('Network', bound='Network')


class Member:
    '''
    Class for modelling an Membership.

    This class is expected to only be used in the podserver
    '''

    def __init__(self, service_id: int, account: Account) -> None:
        '''
        Constructor
        '''

        self.member_id = None
        self.service_id = int(service_id)
        self.account = account
        self.network = self.account.network

        if service_id not in self.network.services:
            raise ValueError(f'Service {service_id} not found')

        self.service = self.network.services[service_id]

        # This is the accepted data contract, which may differ from
        # the current data contract of the service
        self.data_contract = None

        # self.load_schema() will initialize the data property
        self.data = None

        self.paths = copy(self.network.paths)
        self.paths.account_id = account.account_id
        self.paths.account = account.account
        self.paths.service_id = self.service_id

        self.storage_driver = self.paths.storage_driver
        self.document_store: DocumentStore = self.account.document_store

        self.private_key_password = account.private_key_password
        self.tls_secret = None
        self.data_secret = None

    @staticmethod
    def create(service: Service, account: Account, members_ca:
               MembersCaSecret = None):
        '''
        Factory for a new membership
        '''

        member = Member(service.service_id, account)
        member.member_id = uuid4()

        member.tls_secret = MemberSecret(
            member.member_id, member.service_id, member.account
        )
        member.tls_secret = member._create_secret(MemberSecret, members_ca)

        member.data_secret = MemberDataSecret(
            member.member_id, member.service_id, member.account
        )
        member.data_secret = member._create_secret(
            MemberDataSecret, members_ca
        )

        member.data_contract = copy(service.schema)

        filepath = member.paths.get(member.paths.MEMBER_SERVICE_FILE)
        member.data_contract.save(filepath)

        return member

    def _create_secret(self, secret_cls: Callable, issuing_ca: Secret
                       ) -> Secret:
        '''
        Abstraction for creating secrets for the Member class to avoid
        repetition of code for creating the various member secrets of the
        Service class

        :param secret_cls: callable for one of the classes derived from
        byoda.util.secrets.Secret
        :raises: ValueError, NotImplementedError
        '''

        if not self.member_id:
            raise ValueError(
                'Account_id for the account has not been defined'
            )

        if not issuing_ca:
            raise NotImplementedError(
                'Service API for signing member certs is not yet implemented'
            )

        secret = secret_cls(
            self.member_id, self.service_id, account=self.account
        )

        if secret.cert_file_exists():
            raise ValueError(
                f'Cert for {type(secret)} for service {self.service_id} and '
                f'member {self.member_id} already exists'
            )

        if secret.private_key_file_exists():
            raise ValueError(
                f'Private key for {type(secret)} for service {self.service_id}'
                f' and member {self.member_id} already exists'
            )

        if not issuing_ca:
            raise ValueError(
                'Service API for signing certs is not yet available'
            )

        csr = secret.create_csr()
        issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
        certchain = issuing_ca.sign_csr(csr)
        secret.add_signed_cert(certchain)

        secret.save(password=self.private_key_password)

        return secret

    def load_secrets(self):
        '''
        Loads the membership secrets
        '''

        self.tls_secret = MemberSecret(
            None, self.service_id, self.account
        )
        self.tls_secret.load(
            with_private_key=True, password=self.private_key_password
        )
        self.member_id = self.tls_secret.member_id

        self.data_secret = MemberDataSecret(
            self.member_id, self.service_id, self.account
        )
        self.data_secret.load(
            with_private_key=True, password=self.private_key_password
        )

    def load_schema(self):
        '''
        Loads the schema for the service that we're loading the membership for
        '''
        filepath = self.paths.get(self.paths.MEMBER_SERVICE_FILE)
        schema = Schema(
            filepath, self.storage_driver, with_graphql_convert=True
        )
        self.data = MemberData(
            self, schema, self.paths, self.document_store
        )

    def load_data(self):
        '''
        Loads the data stored for the membership
        '''

        self.data.load()

    def save_data(self, data):
        '''
        Saves the data for the membership
        '''

        self.data.save()

    @staticmethod
    def get_data(service_id, path: List[str]) -> Dict:
        '''
        Extracts the requested data field
        '''

        server = config.server
        member = server.account.memberships[service_id]
        member.load_data()

        if not path:
            raise ValueError('Did not get value for path parameter')
        if len(path) > 1:
            raise ValueError(
                f'Got path with more than 1 item: f{", ".join(path)}'
            )

        return member.data.get(path[0])

    @staticmethod
    def set_data(service_id, path: List[str], mutation: GrapheneMutation
                 ) -> None:
        '''
        Sets the provided data

        :param service_id: Service ID for which the GraphQL API was called
        :param path: the GraphQL path variable that shows the path taken
        through the GraphQL data model
        :param mutation: the instance of the Mutation<Object> class
        '''

        server = config.server
        member = server.account.memberships[service_id]

        if not path:
            raise ValueError('Did not get value for path parameter')
        if len(path) > 1:
            raise ValueError(
                f'Got path with more than 1 item: f{", ".join(path)}'
            )

        # Any data we may have in memory may be stale when we run
        # multiple processes so we always need to load the data
        member.load_data()

        # We do not modify existing data as it will need to be validated
        # by JSON Schema before it can be accepted.
        data = copy(member.data)

        # By convention implemented in the Jinja template, the called mutate
        # 'function' starts with the string 'mutate' so we to find out
        # what mutation was invoked, we want what comes after it.
        class_object = path[0][len('mutate'):].lower()

        # Gets the data included in the mutation
        mutate_data = getattr(mutation, class_object)

        # Get the properties of the JSON Schema, we don't support
        # nested objects just yet
        schema = member.data.schema
        schema_properties = schema.json_schema['schema']['properties']

        # The query may be for an object for which we do not yet have
        # any data
        if class_object not in member.data:
            member.data[class_object] = dict()

        properties = schema_properties[class_object].get('properties', {})

        for key in properties.keys():
            if properties[key]['type'] == 'object':
                raise ValueError(
                    'We do not support nested objects yet: %s', key
                )
            if properties[key]['type'] == 'array':
                raise ValueError(
                    'We do not support arrays yet'
                )
            if key.startswith('#'):
                _LOGGER.debug(
                    'Skipping meta-property %s in schema for service %s',
                    key, member.service_id
                )
                continue

            member.data[class_object][key] = getattr(
                mutate_data, key, None
            )

        member.save_data(data)

        return member.data
