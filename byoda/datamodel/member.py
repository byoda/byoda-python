'''
Class for modeling an account on a network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

from uuid import uuid4, UUID
from copy import copy
from typing import Dict, List, TypeVar, Callable, Tuple

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from strawberry.types import Info
from strawberry.fastapi import GraphQLRouter

from byoda.servers.pod_server import PodServer

from byoda.datatypes import CsrSource
from byoda.datatypes import IdType
from byoda.datatypes import StorageType

from byoda.datamodel.service import Service
from byoda.datamodel.memberdata import MemberData
from byoda.datamodel.schema import Schema, SignatureType
from byoda.datamodel.datafilter import DataFilterSet

from byoda.datastore.document_store import DocumentStore

from byoda.storage import FileStorage

from byoda.secrets import ServiceDataSecret
from byoda.secrets import MemberSecret, MemberDataSecret
from byoda.secrets import Secret, MembersCaSecret

from byoda.requestauth.jwt import JWT

from byoda.util.paths import Paths

from byoda.util.nginxconfig import NginxConfig
from byoda.util.nginxconfig import NGINX_SITE_CONFIG_DIR

from byoda import config

from byoda.util.api_client import RestApiClient
from byoda.util.api_client.restapi_client import HttpMethod


_LOGGER = logging.getLogger(__name__)

Account = TypeVar('Account')
Network = TypeVar('Network')

GRAPHQL_API_URL_PREFIX = '/api/v1/data/service-'


class Member:
    '''
    Class for modelling an Membership.

    This class is expected to only be used in the podserver
    '''

    def __init__(self, service_id: int, account: Account,
                 local_service_contract: str = None) -> None:
        '''
        Constructor

        :param service_id: ID of the service
        :param account: account to create the membership for
        :param filepath: this parameter can only be specified by test cases
        '''

        if local_service_contract and not config.test_case:
            raise ValueError(
                'storage_driver and filepath parameters can only be used by '
                'test cases'
            )
        self.member_id: UUID = None
        self.service_id: int = int(service_id)

        self.account: Account = account
        self.network: Network = self.account.network

        self.data: MemberData = None

        self.paths: Paths = copy(self.network.paths)
        self.paths.account_id = account.account_id
        self.paths.account = account.account
        self.paths.service_id = self.service_id

        self.document_store: DocumentStore = self.account.document_store
        self.storage_driver: FileStorage = self.document_store.backend

        self.private_key_password = account.private_key_password

        # The FastAPI app. We store this value to support upgrades of schema
        self.app: FastAPI = None

        if self.service_id not in self.network.services:
            # Here we read the service contract as currently published
            # by the service, which may differ from the one we have
            # previously accepted
            if local_service_contract:
                if not config.test_case:
                    raise ValueError(
                        'Sideloading service contract only supported for '
                        'test cases'
                    )
                filepath = local_service_contract
                verify_signatures = False
            else:
                filepath = self.paths.service_file(self.service_id)
                verify_signatures = True

            try:
                self.service = Service.get_service(
                    self.network, filepath=filepath,
                    verify_signatures=verify_signatures
                )
                if not local_service_contract:
                    self.service.verify_schema_signatures()
            except FileNotFoundError:
                # if the service contract is not yet available for
                # this membership then it should be downloaded at
                # a later point
                _LOGGER.info(
                    f'Service contract file {filepath} does not exist'
                )
                self.service = Service(
                    self.network, service_id=self.service_id,
                )

                self.service.download_data_secret(save=True, failhard=False)

            self.network.services[self.service_id] = self.service

        # This is the schema a.k.a data contract that we have previously
        # accepted, which may differ from the latest schema version offered
        # by the service
        try:
            self.schema: Schema = self.load_schema()
        except FileNotFoundError:
            # We do not have the schema file for a service that the pod did
            # not join yet
            pass

        self.service = self.network.services[service_id]

        # We need the service data secret to verify the signature of the
        # data contract we have previously accepted
        self.service_data_secret = ServiceDataSecret(
            None, service_id, self.network
        )
        if self.service_data_secret.cert_file_exists():
            self.service_data_secret.load(with_private_key=False)
        elif not local_service_contract:
            self.service.download_data_secret(save=True)
            self.service_data_secret.load(with_private_key=False)
        else:
            _LOGGER.debug(
                'Not loading service data secret as we are sideloading the '
                'service contract'
            )

        self.tls_secret = None
        self.data_secret = None

    def as_dict(self) -> Dict:
        '''
        Returns the metdata for the membership, complying with the
        MemberResponseModel
        '''

        if not self.schema:
            raise ValueError('Schema not available')

        data = {
            'account_id': self.account.account_id,
            'network': self.network.name,
            'member_id': self.member_id,
            'service_id': self.service_id,
            'version': self.schema.version,
            'name': self.schema.name,
            'owner': self.schema.owner,
            'website': self.schema.website,
            'supportemail': self.schema.supportemail,
            'description': self.schema.description,
            'certificate': self.tls_secret.cert_as_pem(),
            'private_key': self.tls_secret.private_key_as_pem(),
        }

        return data

    @staticmethod
    def create(service: Service, schema_version: int,
               account: Account, member_id: UUID = None,
               members_ca: MembersCaSecret = None,
               local_service_contract: str = None):
        '''
        Factory for a new membership

        :param service: the service to become a member from
        :param schema_version: the version of the service contract to use
        :param account: the account becoming a member
        :param member_id: the memebr ID
        :param local_service_contract: The service contract to sideload from
        the local file system. This parameter must only be used by test cases
        '''

        if local_service_contract and not config.test_case:
            raise ValueError(
                'storage_driver and filepath parameters can only be used by '
                'test cases'
            )

        member = Member(
            service.service_id, account,
            local_service_contract=local_service_contract
        )
        if member_id:
            if isinstance(member_id, str):
                member.member_id = UUID(member_id)
            elif isinstance(member_id, UUID):
                member.member_id = member_id
            else:
                raise ValueError(f'member_id {member_id} must have type UUID')
        else:
            member.member_id = uuid4()

        # member.create_secrets(members_ca=members_ca)

        if not member.paths.exists(member.paths.SERVICE_FILE):
            filepath = member.paths.get(member.paths.SERVICE_FILE)

        # TODO: make this more user-friendly by attempting to download
        # the specific version of a schema
        if not local_service_contract:
            member.service.download_schema(
                save=True, filepath=member.paths.get(Paths.MEMBER_SERVICE_FILE)
            )

        member.schema = member.load_schema(
            filepath=local_service_contract,
            verify_signatures=not bool(local_service_contract)
        )

        if (member.schema.version != schema_version):
            raise ValueError(
                f'Downloaded schema for service_id {service.service_id} '
                f'has version {member.schema.version} instead of version '
                f'{schema_version} as requested'
            )

        member.tls_secret = MemberSecret(
            member.member_id, member.service_id, member.account
        )
        member.data_secret = MemberDataSecret(
            member.member_id, member.service_id, member.account
        )

        member.create_secrets(members_ca=members_ca)

        member.data_secret.create_shared_key()

        member.data = MemberData(
            member, member.paths, member.document_store
        )
        member.data.initalize()

        member.data.save_protected_shared_key()
        member.data.save()

        filepath = member.paths.get(member.paths.MEMBER_SERVICE_FILE)
        member.schema.save(filepath, member.paths.storage_driver)

        return member

    def create_nginx_config(self):
        '''
        Generates the Nginx virtual server configuration for
        the membership
        '''

        if not self.member_id:
            self.load_secrets()

        self.tls_secret.save_tmp_private_key()

        nginx_config = NginxConfig(
            directory=NGINX_SITE_CONFIG_DIR,
            filename='virtualserver.conf',
            identifier=self.member_id,
            subdomain=f'{IdType.MEMBER.value}{self.service_id}',
            cert_filepath=(
                self.paths.root_directory + '/' + self.tls_secret.cert_file
            ),
            key_filepath=self.tls_secret.unencrypted_private_key_file,
            alias=self.network.paths.account,
            network=self.network.name,
            public_cloud_endpoint=self.paths.storage_driver.get_url(
                StorageType.PUBLIC
            ),
            port=PodServer.HTTP_PORT,
            root_dir=config.server.network.paths.root_directory
        )

        nginx_config.create()
        nginx_config.reload()

    def update_schema(self, version: int):
        '''
        Download the latest version of the schema, disables the old version
        of the schema and enables the new version

        :raises: HTTPException
        '''

        if not self.service:
            raise ValueError(
                'Member instance does not have a service associated'
            )

    def create_secrets(self, members_ca: MembersCaSecret = None) -> None:
        '''
        Creates the secrets for a membership
        '''

        if self.tls_secret and self.tls_secret.cert_file_exists():
            self.tls_secret = MemberSecret(
                None, self.service_id, self.account
            )
            self.tls_secret.load(
                with_private_key=True, password=self.private_key_password
            )
            self.member_id = self.tls_secret.member_id
        else:
            self.tls_secret = self._create_secret(MemberSecret, members_ca)

        if self.data_secret and self.data_secret.cert_file_exists():
            self.data_secret = MemberDataSecret(
                self.member_id, self.service_id, self.account
            )
            self.data_secret.load(
                with_private_key=True, password=self.private_key_password

            )
        else:
            self.data_secret = self._create_secret(
                MemberDataSecret, members_ca
            )

    def _create_secret(self, secret_cls: Callable, issuing_ca: Secret
                       ) -> Secret:
        '''
        Abstraction for creating secrets for the Member class to avoid
        repetition of code for creating the various member secrets of the
        Service class

        :param secret_cls: callable for one of the classes derived from
        byoda.util.secrets.Secret
        :param issuing_ca: ca to sign the cert locally, instead of requiring
        the service to sign the cert request
        :raises: ValueError, NotImplementedError
        '''

        if not self.member_id:
            raise ValueError(
                'Member_id for the account has not been defined'
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
            if secret_cls != MemberSecret and secret_cls != MemberDataSecret:
                raise ValueError(
                    f'No issuing_ca was provided for creating a '
                    f'{type(secret_cls)}'
                )
            else:
                # Get the CSR signed, the resulting cert saved to disk
                # and used to register with both the network and the service
                self.register(secret)

        else:
            csr = secret.create_csr()
            issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
            certchain = issuing_ca.sign_csr(csr)
            secret.from_signed_cert(certchain)
            secret.save(password=self.private_key_password)

        return secret

    def load_secrets(self) -> None:
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

    def create_jwt(self, expiration_days: int = 365) -> JWT:
        '''
        Creates a JWT for a member of a service. This JWT can be
        used to authenticate against the:
        - membership of the pod
        - membership of the service of other pods
        - service
        '''

        jwt = JWT.create(
            self.member_id, IdType.MEMBER, self.tls_secret, self.network.name,
            service_id=self.service_id, expiration_days=expiration_days
        )

        return jwt

    def register(self, secret) -> None:
        '''
        Registers the membership and its schema version with both the network
        and the service. The pod will requests the service to sign its TLS CSR
        '''

        # Register with the service to get our CSR signed
        csr = secret.create_csr()

        payload = {'csr': secret.csr_as_pem(csr).decode('utf-8')}
        resp = RestApiClient.call(
            self.paths.get(Paths.SERVICEMEMBER_API),
            HttpMethod.POST, data=payload
        )
        if resp.status_code != 201:
            raise RuntimeError('Certificate signing request failed')

        cert_data = resp.json()

        secret.from_string(
            cert_data['signed_cert'], certchain=cert_data['cert_chain']
        )
        secret.save(password=self.private_key_password)

        # Register with the Directory server so a DNS record gets
        # created for our membership of the service
        if isinstance(secret, MemberSecret):
            RestApiClient.call(
                self.paths.get(Paths.NETWORKMEMBER_API),
                method=HttpMethod.PUT,
                secret=secret, service_id=self.service_id
            )

            _LOGGER.debug(
                f'Member {self.member_id} registered service '
                f'{self.service_id} with network {self.network.name}'
            )

    def update_registration(self) -> None:
        '''
        Registers the membership and its schema version with both the network
        and the service
        '''

        # Call the member API of the service to update the registration
        RestApiClient.call(
            f'{Paths.SERVICEMEMBER_API}/version/{self.schema.version}',
            method=HttpMethod.PUT, secret=self.tls_secret,
            data={'certchain': self.data_secret.certchain_as_pem()},
            service_id=self.service_id
        )
        _LOGGER.debug(
            f'Member {self.member_id} registered for service '
            f'{self.service_id}'
        )

        RestApiClient.call(
            self.paths.get(Paths.NETWORKMEMBER_API), method=HttpMethod.PUT,
            secret=self.tls_secret, service_id=self.service_id
        )

        _LOGGER.debug(
            f'Member {self.member_id} registered service {self.service_id} '
            f' with network {self.network.name}'
        )

    def load_schema(self, filepath: str = None, verify_signatures: bool = True
                    ) -> Schema:
        '''
        Loads the schema for the service that we're loading the membership for
        '''

        if not filepath:
            filepath = self.paths.get(self.paths.MEMBER_SERVICE_FILE)

        if self.storage_driver.exists(filepath):
            schema = Schema.get_schema(
                filepath, self.storage_driver,
                service_data_secret=self.service.data_secret,
                network_data_secret=self.network.data_secret,
                verify_contract_signatures=verify_signatures
            )
        else:
            _LOGGER.exception(
                f'Service contract file {filepath} does not exist for the '
                'member'
            )
            raise FileNotFoundError(filepath)

        if verify_signatures:
            self.verify_schema_signatures(schema)

        schema.generate_graphql_schema(
            verify_schema_signatures=verify_signatures
        )

        return schema

    def enable_graphql_api(self, app: FastAPI) -> None:
        '''
        Loads the GraphQL API in the FastApi app.
        '''

        self.app = app

        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.schema.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # podserver.dependencies.podrequest_auth.PodApiRequestAuth
        # uses the GRAPHQL_API_URL_PREFIX to evaluate incoming
        # requests
        path = GRAPHQL_API_URL_PREFIX + str(self.service_id)
        graphql_app = GraphQLRouter(self.schema.gql_schema)

        app.include_router(graphql_app, prefix=path)

    def upgrade_graphql_api(self, app: FastAPI) -> None:
        '''
        Updates the GraphQL interface for a membership

        This is not yet implemented as FastAPI has no method for
        replacing an existing route in its list of FastAPI.routes
        '''

        # TODO: implement upgrades of schemas
        # path = f'/api/v1/data/service-{self.service_id}'
        # graphql_app = GraphQLRouter(self.schema.gql_schema)

        # This uses internal data structures of FastAPI as there
        # does not seem to be a supported method to replace an
        # route
        # for route in [r for r in self.app.routes if r.path == path]:
        #    route.endpoint = graphql_app.__init__().get_graphiql

        raise NotImplementedError(
            'Updating a schema is not supported, best short term solution '
            'seems to restart the FastAPI app'
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
            service = Service(
                self.network, service_id=self.service_id,
                storage_driver=self.storage_driver
            )
            service.download_data_secret(save=True)

        schema.verify_signature(
            self.service.data_secret, SignatureType.SERVICE
        )

        _LOGGER.debug(
            f'Verified service signature for service {self.service_id}'
        )

        schema.verify_signature(
            self.network.data_secret, SignatureType.NETWORK
        )

        _LOGGER.debug(
            f'Verified network signature for service {self.service_id}'
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

        self.data.save(data)

    @staticmethod
    def get_data(service_id, info: Info, filters=None) -> Dict:
        '''
        Extracts the requested data field.

        This function is called from the Strawberry code generated by the
        jsonschema-to-graphql converter
        '''

        if not info.path:
            raise ValueError('Did not get value for path parameter')

        if info.path.typename != 'Query':
            raise ValueError(
                f'Got graphql invocation for "{info.path.typename}" '
                f'instead of "Query"'
            )

        _LOGGER.debug(
            f'Got graphql invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        server = config.server
        member = server.account.memberships[service_id]
        member.load_data()

        data = member.data.get(info.path.key)
        if filters:
            if not isinstance(data, list):
                _LOGGER.warning(
                    'Received query with filters for data that is not a list: '
                    f'{member.data}'
                )
            else:
                data: List = DataFilterSet.filter(filters, data)

        return data

    @staticmethod
    def mutate_data(service_id, info: Info) -> None:
        '''
        Mutates the provided data

        :param service_id: Service ID for which the GraphQL API was called
        :param info: the Strawberry 'info' variable
        '''

        if not info.path:
            raise ValueError('Did not get value for path parameter')

        if info.path.typename != 'Mutation':
            raise ValueError(
                f'Got graphql invocation for "{info.path.typename}"" '
                f'instead of "Mutation"'
            )

        _LOGGER.debug(
            f'Got graphql mutation invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        server = config.server
        member = server.account.memberships[service_id]

        # Any data we may have in memory may be stale when we run
        # multiple processes so we always need to load the data
        member.load_data()

        # We do not modify existing data as it will need to be validated
        # by JSON Schema before it can be accepted.
        data = copy(member.data)

        # By convention implemented in the Jinja template, the called mutate
        # 'function' starts with the string 'mutate' so we to find out
        # what mutation was invoked, we want what comes after it.
        class_object = info.path.key[len('mutate_'):].lower()

        # Gets the data included in the mutation
        mutate_data: Dict = info.selected_fields[0].arguments

        # Get the properties of the JSON Schema, we don't support
        # nested objects just yet
        schema = member.schema
        schema_properties = schema.json_schema['jsonschema']['properties']

        # The query may be for an object for which we do not yet have
        # any data
        if class_object not in member.data:
            member.data[class_object] = dict()

        # TODO: refactor to use dataclasses
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

            member.data[class_object][key] = mutate_data[key]

        member.save_data(data)

        return member.data

    def append_data(service_id, info: Info) -> None:
        '''
        Appends the provided data

        :param service_id: Service ID for which the GraphQL API was called
        :param info: the Strawberry 'info' variable
        '''

        if not info.path:
            raise ValueError('Did not get value for path parameter')

        if info.path.typename != 'Mutation':
            raise ValueError(
                f'Got graphql invocation for "{info.path.typename}"" '
                f'instead of "Mutation"'
            )

        _LOGGER.debug(
            f'Got graphql mutation invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        server = config.server
        member = server.account.memberships[service_id]

        # Any data we may have in memory may be stale when we run
        # multiple processes so we always need to load the data
        member.load_data()

        # We do not modify existing data as it will need to be validated
        # by JSON Schema before it can be accepted.
        data = copy(member.data)

        # By convention implemented in the Jinja template, the called mutate
        # 'function' starts with the string 'mutate' so we to find out
        # what mutation was invoked, we want what comes after it.
        class_object = info.path.key[len('append_'):].lower()

        # Gets the data included in the mutation
        mutate_data: Dict = info.selected_fields[0].arguments

        # The query may be for an array for which we do not yet have
        # any data
        if class_object not in member.data:
            member.data[class_object] = []

        # Strawberry passes us data that we can just copy as-is
        member.data[class_object].append(mutate_data)

        member.save_data(data)

        return member.data

    @staticmethod
    def delete_array_data(service_id: int, info: Info, filters) -> Dict:
        '''
        Deletes one or more objects from an array.

        This function is called from the Strawberry code generated by the
        jsonschema-to-graphql converter
        '''

        if not info.path:
            raise ValueError('Did not get value for path parameter')

        if info.path.typename != 'Mutation':
            raise ValueError(
                f'Got graphql invocation for "{info.path.typename}" '
                f'instead of "Mutation"'
            )

        if not filters:
            raise ValueError(
                'Must specify one or more filters to select content for '
                'deletion'
            )

        _LOGGER.debug(
            f'Got graphql invocation for {info.path.typename} '
            f'for object {info.path.key}'
        )

        # By convention implemented in the Jinja template, the called mutate
        # 'function' starts with the string 'delete_from' so we to find out
        # what mutation was invoked, we want what comes after it.
        class_object = info.path.key[len('delete_from_'):].lower()

        server = config.server
        member = server.account.memberships[service_id]
        member.load_data()

        data = copy(member.data.get(class_object))

        if not data:
            return {}

        if not isinstance(data, list):
            _LOGGER.warning(
                'Received query with filters for data that is not a list: '
                f'{member.data}'
            )

        (data, removed) = DataFilterSet.filter_exclude(
            filters, data
        )

        member.data[class_object] = data

        member.save_data(member.data)

        return removed
