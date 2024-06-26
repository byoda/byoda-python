'''
Class for modeling an account on a network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os

from copy import copy
from uuid import UUID
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger

from byoda.datatypes import CsrSource
from byoda.datatypes import IdType
from byoda.datatypes import MemberStatus
from byoda.datatypes import MemberInfo

from byoda.datastore.document_store import DocumentStore

from byoda.datastore.data_store import DataStore
from byoda.datastore.cache_store import CacheStore

from byoda.datamodel.memberdata import MemberData

from byoda.secrets.secret import Secret
from byoda.secrets.account_secret import AccountSecret
from byoda.secrets.data_secret import DataSecret
from byoda.secrets.account_data_secret import AccountDataSecret
from byoda.secrets.networkaccountsca_secret import NetworkAccountsCaSecret
from byoda.secrets.membersca_secret import MembersCaSecret

from byoda.storage.filestorage import FileStorage
from byoda.storage import FileMode

from byoda.util.paths import Paths
from byoda.util.reload import reload_gunicorn
from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.api_client import HttpResponse
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.requestauth.jwt import JWT

from .member import Member
from .service import Service

from byoda import config


_LOGGER: Logger = getLogger(__name__)

Network = TypeVar('Network')


class Account:
    '''
    Class for modelling an account.

    This class is expected to only be used in the podserver
    '''

    __slots__: list[str] = [
        'account', 'password', 'account_id', 'document_store', 'network',
        'private_key_password', 'data_secret', 'tls_secret', 'paths',
        'memberships'
    ]

    def __init__(self,  account_id: str, network: Network,
                 account: str = 'pod') -> None:
        '''
        Constructor
        '''

        _LOGGER.debug(f'Constructing account {account_id}')
        self.account: str = account

        # This is the password to use for HTTP Basic Auth
        self.password: str = None

        if isinstance(account_id, UUID):
            self.account_id: UUID = account_id
        else:
            try:
                self.account_id: UUID = UUID(account_id)
            except ValueError:
                raise ValueError(f'AccountID {account_id} is not a valid UUID')

        self.document_store: DocumentStore = None
        # BUG: should not depend on 'hasattr'
        if hasattr(config.server, 'document_store'):
            self.document_store = config.server.document_store

        self.network: Network = network

        self.private_key_password: str = network.private_key_password

        self.data_secret: DataSecret = AccountDataSecret(
            account_id=self.account_id, network=network
        )

        self.tls_secret: AccountSecret = AccountSecret(
            self.account, self.account_id, self.network
        )

        self.paths: Paths = copy(network.paths)
        self.paths.account = self.account
        self.paths.account_id = self.account_id

        self.memberships: dict[int, Member] = dict()

        _LOGGER.debug(
            f'Initialized account {self.account_id} on '
            f'network {self.network.name}'
        )

    async def create_secrets(self, accounts_ca: NetworkAccountsCaSecret = None,
                             renew: bool = False):
        '''
        Creates the account secret and data secret if they do not already
        exist
        '''

        await self.create_account_secret(accounts_ca, renew=renew)
        await self.create_data_secret(accounts_ca, renew=renew)
        self.data_secret.create_shared_key()
        await self.save_protected_shared_key()

    async def create_account_secret(self,
                                    accounts_ca: NetworkAccountsCaSecret
                                    = None, renew: bool = False) -> bool:
        '''
        Creates the TLS secret for an account.
        '''

        if not self.tls_secret:
            self.tls_secret = AccountSecret(
                self.account, self.account_id, self.network
            )

        if not await self.tls_secret.cert_file_exists() or renew:
            _LOGGER.info(
                f'Creating account secret {self.tls_secret.cert_file}'
            )
            self.tls_secret = await self._create_secret(
                AccountSecret, accounts_ca, renew=renew
            )
            return True

        return False

    async def create_data_secret(self,
                                 accounts_ca: NetworkAccountsCaSecret = None,
                                 renew: bool = False) -> None:
        '''
        Creates the PKI secret used to protect all data in the document store
        '''

        if not self.data_secret:
            self.data_secret = AccountDataSecret(
                self.account, self.account_id, self.network
            )

        if ((not await self.data_secret.cert_file_exists()
                or not self.data_secret.cert) or renew):
            _LOGGER.info(
                f'Creating account data secret {self.data_secret.cert_file}'
            )
            self.data_secret = await self._create_secret(
                AccountDataSecret, accounts_ca, renew=renew
            )

    async def _create_secret(self, secret_cls: callable, issuing_ca: Secret,
                             renew: bool = False) -> Secret:
        '''
        Abstraction for creating secrets for the Service class to avoid
        repetition of code for creating the various member secrets of the
        Service class

        :param secret_cls: callable for one of the classes derived from
        byoda.util.secrets.Secret
        :raises: ValueError, NotImplementedError
        '''

        if not self.account_id:
            raise ValueError(
                'Account_id for the account has not been defined'
            )

        secret: Secret = secret_cls(
            self.account, self.account_id, network=self.network
        )

        if await secret.cert_file_exists():
            if not renew:
                raise ValueError(
                    f'Cert for {type(secret)} for account_id '
                    f'{self.account_id} already exists'
                )
            else:
                _LOGGER.info('Renewing certificate {secret.cert_file}}')

        if await secret.private_key_file_exists():
            if not renew:
                raise ValueError(
                    'Not creating new private key for secret because '
                    f'the renew flag is not set for {type(secret)}'
                )
            await secret.load(with_private_key=True)

        if not issuing_ca:
            if secret_cls != AccountSecret and secret_cls != AccountDataSecret:
                raise ValueError(
                    f'No issuing_ca was provided for creating a '
                    f'{type(secret_cls)}'
                )
            else:
                csr = await secret.create_csr(self.account_id)
                payload: dict[str, str] = {'csr': secret.csr_as_pem(csr)}
                url: str = self.paths.get(Paths.NETWORKACCOUNT_API)

                _LOGGER.debug(f'Getting CSR signed from {url}')
                resp: HttpResponse = await RestApiClient.call(
                    url, method=HttpMethod.POST, data=payload
                )
                if resp.status_code != 201:
                    raise RuntimeError('Certificate signing request failed')

                cert_data: dict[str, str] = resp.json()
                secret.from_string(
                    cert_data['signed_cert'], certchain=cert_data['cert_chain']
                )
        else:
            csr = await secret.create_csr(renew=renew)
            issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
            certchain = issuing_ca.sign_csr(csr)
            secret.from_signed_cert(certchain)

        await secret.save(password=self.private_key_password, overwrite=renew)

        return secret

    async def load_protected_shared_key(self) -> None:
        '''
        Reads the protected symmetric key from file storage. Support
        for changing symmetric keys is currently not supported.
        '''

        filepath: str = self.paths.get(
            self.paths.ACCOUNT_DATA_SHARED_SECRET_FILE
        )

        try:
            protected: str = await self.document_store.backend.read(
                filepath, file_mode=FileMode.BINARY
            )
            self.data_secret.load_shared_key(protected)
        except OSError:
            _LOGGER.error(
                f'Can not read the account protected shared key: {filepath}',
            )
            raise

    async def save_protected_shared_key(self) -> None:
        '''
        Saves the protected symmetric key
        '''

        filepath: str = self.paths.get(
            self.paths.ACCOUNT_DATA_SHARED_SECRET_FILE
        )

        await self.document_store.backend.write(
            filepath, self.data_secret.protected_shared_key,
            file_mode=FileMode.BINARY
        )

    async def load_secrets(self) -> None:
        '''
        Loads the secrets for the account
        '''

        self.tls_secret = AccountSecret(
            self.account, self.account_id, self.network
        )
        await self.tls_secret.load(password=self.private_key_password)

        self.data_secret = AccountDataSecret(
            self.account, self.account_id, self.network
        )
        await self.data_secret.load(password=self.private_key_password)

        # account shared key is required to encrypt the backups
        await self.load_protected_shared_key()

    def create_jwt(self, expiration_seconds: int = 365 * 24 * 60 * 60) -> JWT:
        '''
        Creates a JWT for the account owning the POD. This JWT can be
        used to authenticate only against the pod.

        :param expiration_seconds: the number of seconds the JWT is valid
        :returns: JWT
        '''

        jwt: JWT = JWT.create(
            self.account_id, IdType.ACCOUNT, self.tls_secret,
            self.network.name, service_id=None,
            scope_type=IdType.ACCOUNT, scope_id=self.account_id,
            expiration_seconds=expiration_seconds,
        )
        return jwt

    async def register(self) -> None:
        '''
        Register the pod with the directory server of the network
        '''

        # Register pod to directory server
        url: str = self.paths.get(Paths.NETWORKACCOUNT_API)

        resp: HttpResponse = await RestApiClient.call(
            url, HttpMethod.PUT, self.tls_secret
        )

        _LOGGER.debug(
            f'Registered account with directory server: {resp.status_code}'
        )

    async def load_memberships(self, with_pubsub: bool = True) -> None:
        '''
        Loads the memberships of an account from the storage backend

        :param with_pubsub: should PubSub sockets be created/opened
        '''

        memberships: dict[UUID, MemberInfo] = await self.get_memberships()

        _LOGGER.debug(f'Loading {len(memberships or [])} memberships')

        for membership in memberships.values() or {}:
            member_id: UUID = membership.member_id
            service_id: int = membership.service_id
            if service_id not in self.memberships:
                await self.load_membership(
                    service_id, member_id, with_pubsub=with_pubsub
                )

    async def load_membership(self, service_id: int, member_id: UUID,
                              with_pubsub: bool = True) -> Member:
        '''
        Load the data for a membership of a service

        :param with_pubsub: should PubSub sockets be created/opened
        '''

        _LOGGER.debug(
            f'Loading membership for service_id: {service_id} with '
            f'id {member_id}'
        )

        if service_id in self.memberships:
            raise ValueError(
                f'Already a member of service {service_id}'
            )

        member = Member(service_id, self, member_id=member_id)

        local_service_contract: str | None = os.environ.get(
            'LOCAL_SERVICE_CONTRACT'
        )
        if local_service_contract and not config.debug:
            raise ValueError(
                'LOCAL_SERVICE_CONTRACT is set but config.debug is not set'
            )

        await member.setup(
            local_service_contract=local_service_contract, new_membership=False
        )

        member.schema.get_data_classes(with_pubsub=with_pubsub)

        data_store: DataStore = config.server.data_store
        await data_store.setup_member_db(
                member.member_id, member.service_id, member.schema
        )

        cache_store: CacheStore = config.server.cache_store
        await cache_store.setup_member_db(
                member.member_id, member.service_id, member.schema
        )

        member.data = MemberData(member)

        if not member.tls_secret or not member.data_secret:
            await member.load_secrets()

        if not member.service_ca_certchain:
            await member.load_service_cacert()

        if not member.query_cache:
            await member.create_query_cache()

        if not member.counter_cache:
            await member.create_counter_cache()

        if not member.data_secret.shared_key:
            await member.data.load_protected_shared_key()

        self.memberships[service_id] = member

        return member

    async def update_memberships(self, data_store: DataStore,
                                 cache_store: CacheStore,
                                 with_pubsub: bool = False) -> None:
        '''
        Gets the current memberships of the local pod from storage to
        update the memberships that are already in memory. This method
        can be used if other processes update the memberships in storage

        :param data_store: the data store to set up the new memberships
        :param cahce_store: the cache store to set up the new memberships
        :param with_pubsub: should pubsub sockets be created for the new
        memberships
        :returns: (none)
        '''

        memberships_in_storage: dict[UUID, MemberInfo] = \
            await self.get_memberships(status=MemberStatus.ACTIVE)

        _LOGGER.debug(
            f'Found {len(memberships_in_storage or [])} memberships in storage'
        )

        new_membership_count: int = 0
        for member_info in memberships_in_storage.values():
            service_id: int = member_info.service_id
            member_id: UUID = member_info.member_id
            if service_id not in self.memberships:
                member: Member = await self.load_membership(
                    service_id, member_id, with_pubsub=with_pubsub
                )
                await data_store.setup_member_db(
                    member.member_id, member.service_id, member.schema
                )
                await cache_store.setup_member_db(
                    member.member_id, member.service_id, member.schema
                )
                new_membership_count += 1

        _LOGGER.debug(
            f'Found {new_membership_count} memberships not yet in memory'
        )

    async def get_memberships(self, status: MemberStatus = MemberStatus.ACTIVE
                              ) -> dict[UUID, MemberInfo]:
        '''
        Get a list of the service_ids that the pod has joined by looking
        at storage.

        :returns: dict of membership UUID with as value a dict with keys
        member_id, service_id, status, timestamp,
        '''

        data_store: DataStore = config.server.data_store
        memberships: dict[UUID, MemberInfo] = \
            await data_store.backend.get_memberships(status)

        _LOGGER.debug(
            f'Got {len(memberships or [])} memberships with '
            f'status {status} from account DB'
        )

        return memberships

    async def get_membership(self, service_id: int, with_pubsub: bool = True
                             ) -> Member | None:
        '''
        Get the membership of a service, loading the memberships from storage
        if it is not already cached

        :param service_id: The ID of the service to get the membership for
        :returns: The membership object or None if the account doesn't have
        a membership for the service
        '''

        service_id = int(service_id)

        if service_id not in self.memberships:
            await self.load_memberships(with_pubsub=with_pubsub)

        return self.memberships.get(service_id)

    async def join(self, service_id: int, schema_version: int,
                   local_storage: FileStorage,
                   members_ca: MembersCaSecret = None, member_id: UUID = None,
                   local_service_contract: str = None, with_reload: bool = True
                   ) -> Member:
        '''
        Join a service for the first time

        :param service_id: The ID of the service to join
        :param schema_version: the version of the schema that has been accepted
        :param local_storage:
        :param members_ca: The CA to sign the member secret. This parameter is
        only used for test cases
        :param member_id: The UUID to use for the member_id
        :param local_service_contract: service contract to side-load. This
        parameter must only be specified by test cases
        '''

        if (local_service_contract or members_ca) and not config.test_case:
            raise ValueError(
                'storage_driver, filepath, and members_ca parameters can '
                'only be specified by test cases'
            )

        service_id = int(service_id)

        service = Service(service_id=service_id, network=self.network)
        if local_service_contract:
            await service.examine_servicecontract(local_service_contract)

        member: Member = await Member.create(
            service, schema_version, self, local_storage, member_id=member_id,
            members_ca=members_ca,
            local_service_contract=local_service_contract
        )

        await member.load_service_cacert()

        await member.load_secrets()

        member.schema.get_data_classes()

        # Save secret to local disk as it is needed by ApiClient for
        # registration
        await member.tls_secret.save(
            self.private_key_password, overwrite=True,
            storage_driver=local_storage
        )
        member.tls_secret.save_tmp_private_key()

        # Save ASAP so apps can download it for extern-JWT validation
        await member.data_secret.save(
            self.private_key_password, overwrite=True,
            storage_driver=local_storage
        )

        # Edge-case where pod already has a cert for the membership
        if member.tls_secret.cert:
            await member.update_registration()

        await member.create_query_cache()
        await member.create_counter_cache()

        await member.create_angie_config()

        if with_reload:
            reload_gunicorn()

        self.memberships[service_id] = member

        return member
