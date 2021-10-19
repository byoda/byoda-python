'''
Class for modeling an account on a network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

from byoda.util.secrets.service_secret import ServiceSecret
import logging

from uuid import uuid4, UUID
from copy import copy
from typing import List, Dict, TypeVar, Callable

from graphene import Mutation as GrapheneMutation

from byoda.datatypes import CsrSource, CloudType, IdType

from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema, SignatureType
from byoda.datamodel.memberdata import MemberData

from byoda.datastore.document_store import DocumentStore

from byoda.storage import FileStorage

from byoda.util.secrets import MemberSecret, MemberDataSecret
from byoda.util.secrets import Secret, MembersCaSecret

from byoda.util import Paths
from podserver.bootstrap import NginxConfig, NGINX_SITE_CONFIG_DIR

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

        self.member_id: UUID = None
        self.service_id: int = int(service_id)
        self.account: Account = account
        self.network: Network = self.account.network

        if service_id not in self.network.services:
            raise ValueError(f'Service {service_id} not found')

        self.service = self.network.services[service_id]

        # self.load_schema() will initialize the data property
        self.data: Dict = None

        self.paths: Paths = copy(self.network.paths)
        self.paths.account_id = account.account_id
        self.paths.account = account.account
        self.paths.service_id = self.service_id

        self.storage_driver: FileStorage = self.paths.storage_driver
        self.document_store: DocumentStore = self.account.document_store

        self.private_key_password = account.private_key_password

        # This is the schema a.k.a data contract that we have previously
        # accepted, which may differ from the latest schema version offered
        # by the service
        self.schema: Schema = None

        # We need the service data secret to verify the signature of the
        # data contract we have previously accepted
        # TODO: load the service data secret through an API from the service
        self.service_data_secret = ServiceSecret(
            None, service_id, self.network
        )
        self.service_data_secret.load(with_private_key=False)

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

        member.schema = copy(service.schema)

        filepath = member.paths.get(member.paths.MEMBER_SERVICE_FILE)
        member.schema.save(filepath, member.paths.storage_driver)

        if config.server.cloud != CloudType.LOCAL:
            nginx_config = NginxConfig(
                directory=NGINX_SITE_CONFIG_DIR,
                filename='virtualserver.conf',
                identifier=member.member_id,
                subdomain=f'{IdType.MEMBER.value}-{member.service_id}',
                cert_filepath='',
                key_filepath='',
                alias=account.network.paths.account,
                network=account.network.name,
                public_cloud_endpoint=member.paths.storage_driver.get_url(
                    public=True
                ),
            )

            if not nginx_config.exists():
                nginx_config.create()
                nginx_config.reload()

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

        # TODO: SECURITY: add constraints
        csr = secret.create_csr()
        issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
        certchain = issuing_ca.sign_csr(csr)
        secret.from_signed_cert(certchain)

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
        schema = Schema.get_schema(filepath, self.storage_driver)
        self.verify_schema_signatures(schema)
        schema.generate_graphql_schema()

        self.data = MemberData(
            self, schema, self.paths, self.document_store
        )

    def verify_schema_signatures(self, schema: Schema):
        '''
        Verify the signatures for the schema, a.k.a. data contract

        :raises: ValueError
        '''

        if not schema.signatures[SignatureType.SERVICE.value]:
            raise ValueError('Schema does not contain a service signature')

        if not schema.signatures[SignatureType.NETWORK.value]:
            raise ValueError('Schema does not contain a network signature')

        if not self.service.data_secret or not self.service.data_secret.cert:
            raise ValueError(
                'Data secret not available to verify service signature'
            )

        if not self.network.data_secret or not self.network.data_secret.cert:
            raise ValueError(
                'Network data secret not available to verify network signature'
            )

        schema.verify_signature(
            self.service.data_secret, SignatureType.SERVICE
        )

        _LOGGER.debug(
            'Verified service signature for service %s', self.service_id
        )

        schema.verify_signature(
            self.network.data_secret, SignatureType.NETWORK
        )

        _LOGGER.debug(
            'Verified network signature for service %s', self.service_id
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
        schema_properties = schema.json_schema['jsonschema']['properties']

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
