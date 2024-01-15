'''
Class for modeling an account on a network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''


from copy import copy
from uuid import UUID
from uuid import uuid4
from typing import Self
from typing import TypeVar
from logging import getLogger
from datetime import datetime

from fastapi import FastAPI

from byoda.datamodel.service import Service
from byoda.datamodel.memberdata import MemberData
from byoda.datamodel.schema import Schema, SignatureType
from byoda.datamodel.schema import SchemaDataItem

from byoda.datatypes import CsrSource
from byoda.datatypes import IdType
from byoda.datatypes import StorageType
from byoda.datatypes import NetworkLink

from byoda.datastore.document_store import DocumentStore
from byoda.datastore.data_store import DataStore
from byoda.datastore.cache_store import CacheStore

from byoda.datacache.querycache import QueryCache
from byoda.datacache.counter_cache import CounterCache

from byoda.storage import FileStorage


from byoda.secrets.serviceca_secret import ServiceCaSecret
from byoda.secrets.service_data_secret import ServiceDataSecret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_secret import CertificateSigningRequest
from byoda.secrets.member_data_secret import MemberDataSecret
from byoda.secrets.secret import Secret
from byoda.secrets.membersca_secret import MembersCaSecret

from byoda.requestauth.jwt import JWT

from byoda.servers.pod_server import PodServer

from byoda.util.paths import Paths

from byoda.util.fastapi import update_cors_origins

from byoda.util.angieconfig import AngieConfig
from byoda.util.angieconfig import ANGIE_SITE_CONFIG_DIR

from byoda.util.logger import Logger

from byoda import config

from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.restapi_client import HttpMethod
from byoda.util.api_client.restapi_client import HttpResponse

_LOGGER: Logger = getLogger(__name__)

LETSENCRYPT_ROOT_DIR = '/etc/letsencrypt/live'

Account = TypeVar('Account')
Network = TypeVar('Network')
Server = TypeVar('Server')


class Member:
    '''
    Class for modelling an Membership.

    This class is expected to only be used in the podserver
    '''

    __slots__: list[str] = [
        'member_id', 'service_id', 'account', 'network', 'service', 'schema',
        'data', 'paths', 'document_store', 'data_store', 'cache_store',
        'query_cache', 'counter_cache', 'storage_driver',
        'private_key_password', 'tls_secret', 'data_secret',
        'service_data_secret', 'service_ca_secret', 'service_ca_certchain',
        'joined', 'schema_versions', 'auto_upgrade'

    ]

    def __init__(self, service_id: int, account: Account,
                 local_service_contract: str = None, member_id: UUID = None
                 ) -> None:
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

        self.member_id: UUID = member_id
        self.service_id: int = int(service_id)

        self.account: Account = account
        self.network: Network = account.network

        self.schema: Schema | None = None

        # These 3 fields are retrieved from the 'Member' object in the
        # datastore
        self.joined: datetime | None = None
        # What we tell others on which versions of the schema we support
        self.schema_versions: list[int] = []
        # Should  we automatically upgrade to new versions of the service
        # contract when they become available
        # TODO: needs to be implemented in the podworker
        self.auto_upgrade: bool = False

        self.data: MemberData | None = None

        self.paths: Paths = copy(account.paths)
        self.paths.account_id: UUID = account.account_id
        self.paths.account: str = account.account
        self.paths.service_id: int = self.service_id

        self.document_store: DocumentStore = self.account.document_store
        self.data_store: DataStore = config.server.data_store
        self.cache_store: CacheStore = config.server.cache_store

        self.query_cache: QueryCache | None = None
        self.counter_cache: CounterCache | None = None

        self.storage_driver: FileStorage = self.document_store.backend

        self.private_key_password: str = account.private_key_password

        self.tls_secret: MemberSecret | None = None
        self.data_secret: MemberDataSecret | None = None
        self.service_data_secret: ServiceDataSecret | None = None
        self.service_ca_secret: ServiceCaSecret | None = None
        # This is the cert chain up to but excluding the network root CA
        self.service_ca_certchain: ServiceCaSecret | None = None

        _LOGGER.debug(
            f'Instantiated membership {self.member_id} for '
            f'service {self.service_id}'
        )

    async def setup(self, local_service_contract: str = None,
                    new_membership: bool = True) -> None:
        '''
        Sets up a membership for use by the pod. This method is expected
        to only be called by the appserver or workers on the pod, or test
        cases simulating them.
        Directory-, service- and other servers should not call this method.

        '''

        if local_service_contract:
            verify_signatures = False
        else:
            verify_signatures = True

        filepath: str = self.paths.service_file(self.service_id)
        network: Network = self.network
        if self.service_id not in self.network.services:
            # Here we read the service contract as currently published
            # by the service, which may differ from the one we have
            # previously accepted
            _LOGGER.debug(
                f'Setting up membership for service {self.service_id}'
            )
            if local_service_contract:
                if not config.test_case:
                    raise ValueError(
                        'Sideloading service contract only supported for '
                        'test cases'
                    )
                filepath: str = local_service_contract
            else:
                if new_membership:
                    _LOGGER.debug('Setting up new membership')
                    filepath: str = self.paths.service_file(self.service_id)
                else:
                    _LOGGER.debug('Setting up existing membership')
                    filepath: str = self.paths.member_service_file(
                        self.service_id
                    )

                _LOGGER.debug(f'Setting service contract file to {filepath}')

            try:
                _LOGGER.debug(
                    f'Setting up service {self.service_id} from {filepath} '
                    'without loading the schema'
                )
                self.service = await Service.get_service(
                    network, filepath=filepath,
                    verify_signatures=verify_signatures,
                    load_schema=False
                )
            except FileNotFoundError:
                # if the service contract is not yet available for
                # this membership then it should be downloaded at
                # a later point
                _LOGGER.info(
                    f'Service contract file {filepath} does not exist'
                )
                self.service = Service(
                    network, service_id=self.service_id,
                )

            network.services[self.service_id] = self.service
        else:
            _LOGGER.debug(
                f'Membership for {self.service_id} already in memory'
            )
            self.service: Service = network.services[self.service_id]

        if not self.service.data_secret:
            await self.service.download_data_secret(
                save=True, failhard=False
            )

        self.service_data_secret: ServiceDataSecret = self.service.data_secret

        # This is the schema a.k.a data contract that we have previously
        # accepted, which may differ from the latest schema version offered
        # by the service
        try:
            if new_membership and not local_service_contract:
                await self.service.download_schema(
                    save=True, filepath=filepath
                )

            self.schema: Schema = await self.load_schema(
                filepath=filepath, verify_signatures=verify_signatures,
            )
        except FileNotFoundError:
            # We do not have the schema file for a service that the pod did
            # not join yet
            if not new_membership:
                raise RuntimeError(
                    'Did not find schema for a service we are already '
                    'a member of'
                )

        # FIXME: 13 lines above this, we already downloaded the service
        # DataSecret and assigned it to self.service_data_secret

        # We need the service data secret to verify the signature of the
        # data contract we have previously accepted
        self.service_data_secret = ServiceDataSecret(
            self.service_id, self.network
        )
        if await self.service_data_secret.cert_file_exists():
            await self.service_data_secret.load(with_private_key=False)
        elif not local_service_contract:
            await self.service.download_data_secret(save=True)
            await self.service_data_secret.load(with_private_key=False)
        else:
            _LOGGER.debug(
                'Not loading service data secret as we are sideloading the '
                'service contract'
            )

    async def load_member_settings(self) -> None:
        '''
        Loads the member settings for the membership from the 'member'
        object in the service contract.
        '''

        _LOGGER.debug('Loading member settings')
        self.data.load_member_settings

    def as_dict(self) -> dict:
        '''
        Returns the metdata for the membership, complying with the
        MemberResponseModel
        '''

        if not self.schema:
            raise ValueError('Schema not available')

        data: dict[str, str | int | UUID] = {
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
    async def create(service: Service, schema_version: int,
                     account: Account, local_storage: FileStorage,
                     member_id: UUID = None,
                     members_ca: MembersCaSecret = None,
                     local_service_contract: str = None) -> Self:
        '''
        Factory for a new membership

        :param service: the service to become a member from
        :param schema_version: the version of the service contract to use
        :param account: the account becoming a member
        :param local_storage:
        :param member_id: the memebr ID
        :param members_ca: the CA to sign the member cert with, only used
        for test cases
        :param local_service_contract: The service contract to sideload from
        the local file system. This parameter must only be used by test cases
        '''

        if local_service_contract and not config.test_case:
            raise ValueError(
                'storage_driver and filepath parameters can only be used by '
                'test cases'
            )

        _LOGGER.debug('Creating membership')
        member = Member(
            service.service_id, account,
            local_service_contract=local_service_contract,
        )
        await member.setup(
            local_service_contract=local_service_contract, new_membership=True
        )

        if member_id:
            if isinstance(member_id, str):
                member.member_id = UUID(member_id)
            elif isinstance(member_id, UUID):
                member.member_id = member_id
            else:
                raise ValueError(
                    f'member_id {member_id} must have type UUID or str'
                )
        else:
            _LOGGER.debug(f'Creating new member_id: {member_id}')
            member.member_id = uuid4()

        _LOGGER.debug(f'New member ID {member.member_id}')
        if not await member.paths.exists(member.paths.SERVICE_FILE):
            filepath = member.paths.get(member.paths.SERVICE_FILE)

        if (member.schema.version != schema_version):
            raise ValueError(
                f'Downloaded schema for service_id {service.service_id} '
                f'has version {member.schema.version} instead of version '
                f'{schema_version} as requested'
            )

        member.tls_secret = MemberSecret(
            member.member_id, member.service_id, account=member.account
        )

        member.data_secret = MemberDataSecret(
            member.member_id, member.service_id, account=member.account
        )

        _LOGGER.debug(f'Creating member secrets for member {member.member_id}')
        await member.create_secrets(local_storage, members_ca=members_ca)

        member.data_secret.create_shared_key()

        member.data = MemberData(member)

        await member.data.save_protected_shared_key()

        filepath: str = member.paths.get(member.paths.MEMBER_SERVICE_FILE)
        await member.schema.save(filepath, member.paths.storage_driver)

        return member

    async def create_query_cache(self) -> None:
        '''
        Sets up the query cache for the membership
        '''

        _LOGGER.debug('Creating query cache for membership')
        self.query_cache = await QueryCache.create(self)

    async def create_counter_cache(self) -> None:
        '''
        Sets up the counter cache for the membership
        '''

        _LOGGER.debug('Creating counter cache for membership')
        self.counter_cache = await CounterCache.create(self)

    async def create_angie_config(self) -> None:
        '''
        Generates the Angie virtual server configuration for
        the membership
        '''

        if not self.member_id:
            self.load_secrets()

        server: PodServer = config.server
        cloud: str = server.cloud.value

        angie_config = AngieConfig(
            directory=ANGIE_SITE_CONFIG_DIR,
            filename='virtualserver.conf',
            identifier=self.member_id,
            subdomain=f'{IdType.MEMBER.value}{self.service_id}',
            cert_filepath=(
                self.paths.root_directory + '/' + self.tls_secret.cert_file
            ),
            key_filepath=self.tls_secret.get_tmp_private_key_filepath(),
            alias=self.network.paths.account,
            network=self.network.name,
            public_cloud_endpoint=self.paths.storage_driver.get_url(
                storage_type=StorageType.PUBLIC
            ),
            restricted_cloud_endpoint=self.paths.storage_driver.get_url(
                storage_type=StorageType.RESTRICTED
            ),
            private_cloud_endpoint=self.paths.storage_driver.get_url(
                storage_type=StorageType.PRIVATE
            ),
            cloud=cloud,
            port=PodServer.HTTP_PORT,
            service_id=self.service_id,
            root_dir=config.server.network.paths.root_directory,
            custom_domain=None,
            shared_webserver=config.server.shared_webserver,
            public_bucket=self.paths.storage_driver.get_bucket(
                StorageType.PUBLIC
            ),
            restricted_bucket=self.paths.storage_driver.get_bucket(
                StorageType.RESTRICTED
            ),
            private_bucket=self.paths.storage_driver.get_bucket(
                StorageType.PRIVATE
            ),
        )

        angie_config.create()
        angie_config.reload()

    def update_schema(self, version: int) -> None:
        '''
        Download the latest version of the schema, disables the old version
        of the schema and enables the new version

        :raises: HTTPException
        '''

        if not self.service:
            raise ValueError(
                'Member instance does not have a service associated'
            )

        raise NotImplementedError(
            'Schema updates are not yet supported by the pod'
        )

    def get_data_class(self, class_name: str) -> SchemaDataItem:
        '''
        Gets the data class

        :param class_name: name of the class to get
        '''

        return self.schema.get_data_class(class_name)

    async def create_secrets(self, local_storage: FileStorage,
                             members_ca: MembersCaSecret = None) -> None:
        '''
        Creates the secrets for a membership
        '''

        if self.tls_secret and await self.tls_secret.cert_file_exists():
            self.tls_secret = MemberSecret(
                None, self.service_id, self.account
            )
            _LOGGER.debug('Loading member TLS secret')
            await self.tls_secret.load(
                with_private_key=True, password=self.private_key_password
            )
            self.member_id = self.tls_secret.member_id
        else:
            _LOGGER.debug('Creating member TLS secret')
            self.tls_secret = await self._create_secret(
                MemberSecret, members_ca
            )

        _LOGGER.debug('Saving MemberSecret to local storage')
        await self.tls_secret.save(
             password=self.private_key_password, overwrite=True,
             storage_driver=local_storage
        )
        self.tls_secret.save_tmp_private_key()

        if self.data_secret and await self.data_secret.cert_file_exists():
            self.data_secret = MemberDataSecret(
                self.member_id, self.service_id, self.account
            )
            _LOGGER.debug('Loading member data secret')
            await self.data_secret.load(
                with_private_key=True, password=self.private_key_password

            )
        else:
            _LOGGER.debug('Creating member data secret')
            self.data_secret = await self._create_secret(
                MemberDataSecret, members_ca
            )

        _LOGGER.debug('Saving MemberDataSecret to local storage')
        await self.data_secret.save(
             password=self.private_key_password, overwrite=True,
             storage_driver=local_storage
        )

    async def _create_secret(self, secret_cls: callable, issuing_ca: Secret,
                             renew: bool = False) -> Secret:
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
            self.member_id, self.service_id, self.account
        )

        if await secret.cert_file_exists():
            if not renew:
                raise ValueError(
                    f'Cert for {type(secret)} for account_id '
                    f'{self.account_id} already exists'
                )

        if await secret.private_key_file_exists():
            if not renew:
                raise ValueError(
                    'Not creating new private key for secret because '
                    f'the renew flag is not set for {type(secret)}'
                )
            secret.load(with_private_key=True)

        if not issuing_ca:
            if secret_cls != MemberSecret and secret_cls != MemberDataSecret:
                raise ValueError(
                    f'No issuing_ca was provided for creating a '
                    f'{type(secret_cls)}'
                )
            else:
                # Get the CSR signed, the resulting cert saved to disk
                # and used to register with both the network and the service
                await self.register(secret)

        else:
            csr = await secret.create_csr()
            issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
            certchain = issuing_ca.sign_csr(csr)
            secret.from_signed_cert(certchain)
            await secret.save(password=self.private_key_password)

        return secret

    async def load_secrets(self) -> None:
        '''
        Loads the membership secrets from the cloud
        '''

        self.tls_secret = MemberSecret(
            None, self.service_id, self.account
        )
        await self.tls_secret.load(
            with_private_key=True, password=self.private_key_password
        )
        self.member_id = self.tls_secret.member_id

        self.data_secret = MemberDataSecret(self.member_id, self.service_id)
        await self.data_secret.load(
            with_private_key=True, password=self.private_key_password
        )

    def create_jwt(self, target_id: UUID = None, target_type: IdType = None,
                   expiration_days: int = 365) -> JWT:
        '''
        Creates a JWT for a member of a service. Depending on the id_type,
        this JWT can be used to authenticate against:
        - membership of this pod
        - a service
        - an app

        :params target_id: The UUID of the server that will use this JWT
        to authenticate a request. If not provided, it will default to
        the member_id of this Member instance
        :param target_type: The type of server that will use this JWT to
        authenticate a request. If not provided, it will default to
        IdType.MEMBER
        :param expiration_days:
        :raises: ValueError
        '''

        if not isinstance(expiration_days, int):
            raise ValueError(
                'expiration_days must be an integer, not '
                f'{type(expiration_days)}'
            )

        if bool(target_id) != bool(target_type):
            raise ValueError(
                'Either target_id or target_type must be set or neither '
                f'must be set: {target_id} - {target_type}'
            )

        if not target_id:
            target_id: UUID = self.member_id
            target_type: IdType = IdType.MEMBER

        jwt = JWT.create(
            self.member_id, IdType.MEMBER, self.data_secret, self.network.name,
            service_id=self.service_id, scope_type=target_type,
            scope_id=target_id, expiration_days=expiration_days,
        )

        return jwt

    async def register(self, secret: MemberSecret | MemberDataSecret) -> None:
        '''
        Registers the membership and its schema version with both the network
        and the service. The pod will requests the service to sign its TLS CSR
        '''

        _LOGGER.debug('Registering the pod with the network and service')
        # Register with the service to get our CSR signed
        csr: CertificateSigningRequest = await secret.create_csr()

        payload: dict[str, str] = {'csr': secret.csr_as_pem(csr)}
        resp: HttpResponse = await RestApiClient.call(
            self.paths.get(Paths.SERVICEMEMBER_API),
            HttpMethod.POST, data=payload
        )
        if resp.status_code != 201:
            raise RuntimeError('Certificate signing request failed')

        cert_data: dict[str, any] = resp.json()

        secret.from_string(
            cert_data['signed_cert'], certchain=cert_data['cert_chain']
        )
        await secret.save(password=self.private_key_password)

        # Register with the Directory server so a DNS record gets
        # created for our membership of the service
        server: Server = config.server
        await secret.save(
            password=self.private_key_password, overwrite=True,
            storage_driver=server.local_storage
        )

        if isinstance(secret, MemberSecret):
            secret.save_tmp_private_key()
            await RestApiClient.call(
                self.paths.get(Paths.NETWORKMEMBER_API),
                method=HttpMethod.PUT,
                secret=secret, service_id=self.service_id
            )

            _LOGGER.debug(
                f'Member {self.member_id} registered service '
                f'{self.service_id} with network {self.network.name}'
            )

    async def update_registration(self) -> None:
        '''
        Registers the membership and its schema version with both the network
        and the service
        '''

        # Call the member API of the service to update the registration
        await RestApiClient.call(
            f'{Paths.SERVICEMEMBER_API}/version/{self.schema.version}',
            method=HttpMethod.PUT, secret=self.tls_secret,
            data={'certchain': self.data_secret.certchain_as_pem()},
            service_id=self.service_id
        )
        _LOGGER.debug(
            f'Member {self.member_id} updated registration for service '
            f'{self.service_id}'
        )

        await RestApiClient.call(
            self.paths.get(Paths.NETWORKMEMBER_API), method=HttpMethod.PUT,
            secret=self.tls_secret, service_id=self.service_id
        )

        _LOGGER.debug(
            f'Member {self.member_id} updated registration with service '
            f'{self.service_id}  with network {self.network.name}'
        )

    async def load_service_cacert(self) -> None:
        '''
        Downloads the Service CA cert and writes it to local
        storage for us by the angie configuration for the membership
        '''

        server: Server = config.server

        self.service_ca_certchain = ServiceCaSecret(
            self.service_id, self.network
        )
        self.service_ca_certchain.cert_file = self.paths.get(
            Paths.SERVICE_CA_CERTCHAIN_FILE
        )
        try:
            await self.service_ca_certchain.load(
                with_private_key=False, storage_driver=server.local_storage
            )
            return
        except FileNotFoundError:
            _LOGGER.debug(
                'Did not find local Service CA cert so will download it'
            )

        # The downloaded cert downloaded here is the complete certchain from
        # the Service CA to the root CA, including the self-signed root CA
        # cert. The file is hosted by the angie configuration for the
        # Service server, in the 'ssl_client_certificate' directive.
        resp: HttpResponse = await ApiClient.call(
            Paths.SERVICE_CACERT_DOWNLOAD,
            service_id=self.service_id,
            network_name=self.network.name
        )
        if resp.status_code != 200:
            raise ValueError(
                'No service CA cert available locally or from the '
                'service'
            )

        self.service_ca_certchain.from_string(resp.text)

        await self.service_ca_certchain.save(
            storage_driver=server.local_storage, overwrite=True
        )

    async def load_schema(self, filepath: str = None,
                          verify_signatures: bool = True) -> Schema:
        '''
        Loads the schema for the service that we're loading the membership for

        :param filepath: The path to the schema file. If not provided, schema
        will be read from the default location
        '''

        if not filepath:
            filepath = self.paths.get(self.paths.MEMBER_SERVICE_FILE)

        if await self.storage_driver.exists(filepath):
            schema: Schema = await Schema.get_schema(
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

        _LOGGER.debug(f'Loading schema at {filepath}')
        if verify_signatures:
            await self.verify_schema_signatures(schema)
        else:
            _LOGGER.debug('Not verifying schema signatures')

        return schema

    async def load_settings(self) -> None:
        '''
        Loads the settings for the membership from the 'Member' data classs

        :returns: (none)
        :raises ValueError: if the data class for the member settings has
        no values
        '''

        member_settings: dict[str, any] = \
            await self.data.load_member_settings()

        self.joined = member_settings['joined']
        self.schema_versions = member_settings['schema_versions']
        self.auto_upgrade = member_settings['auto_upgrade']

    async def enable_data_apis(self, app: FastAPI, data_store: DataStore,
                               cache_store: CacheStore) -> None:
        '''
        Generate the data classes for the schema and the
        corresponding storage tables
        Enables the Data APIs that were generated for
        the schema of the service
        '''

        _LOGGER.debug('Enabling data APIs')

        update_cors_origins(self.schema.cors_origins)

        schema: Schema = self.schema

        await data_store.setup_member_db(
            self.member_id, self.service_id, self.schema
        )

        await cache_store.setup_member_db(
            self.member_id, self.service_id, self.schema
        )

        schema.enable_data_apis(app)

    async def verify_schema_signatures(self, schema: Schema) -> None:
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
            await service.download_data_secret(save=True)

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

    async def load_network_links(self) -> list[NetworkLink]:
        '''
        Loads the network links of the membership
        '''

        return await self.data.load_network_links()

    async def load_data(self, key: str, filters: list[str] = None) -> None:
        '''
        Loads the data stored for the membership
        '''

        await self.data.load(key, filters)

    async def save_data(self, data) -> None:
        '''
        Saves the data for the membership
        '''

        _LOGGER.debug(f'Saving member data of {len(data)} bytes')
        await self.data.save(data)

    async def download_secret(self, member_id: UUID = None) -> MemberSecret:

        if not member_id:
            member_id = self.member_id
        elif isinstance(member_id, str):
            member_id = UUID(member_id)

        fqdn: str = MemberSecret.create_commonname(
            member_id, self.service_id, self.network.name
        )
        resp: HttpResponse = await ApiClient.call(
            f'https://{fqdn}/member-cert.pem'
        )

        if resp.status_code != 200:
            raise RuntimeError(
                'Download the member cert resulted in status: '
                f'{resp.status_code}'
            )

        certchain: str = resp.text

        secret = MemberSecret(member_id, self.service_id, self.account)
        secret.from_string(certchain)

        return secret
