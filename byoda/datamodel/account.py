'''
Class for modeling an account on a network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from uuid import UUID
from typing import TypeVar, Callable, Dict, Set
from copy import copy

import requests

from byoda.datatypes import CsrSource
from byoda.datatypes import IdType
from byoda.datastore.document_store import DocumentStore
from byoda.datamodel.memberdata import MemberData

from byoda.secrets import Secret
from byoda.secrets import AccountSecret
from byoda.secrets import DataSecret
from byoda.secrets import AccountDataSecret
from byoda.secrets import NetworkAccountsCaSecret
from byoda.secrets import MembersCaSecret

from byoda.util.paths import Paths
from byoda.util.api_client import RestApiClient
from byoda.util.api_client.restapi_client import HttpMethod

from byoda.requestauth.jwt import JWT

from .member import Member
from .service import Service

from byoda import config


_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network')


class Account:
    '''
    Class for modelling an account.

    This class is expected to only be used in the podserver
    '''

    def __init__(self,  account_id: str, network: Network,
                 account: str = 'pod'):
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

        self.memberships: Dict[int, Member] = dict()

    async def create_secrets(self, accounts_ca: NetworkAccountsCaSecret = None
                             ):
        '''
        Creates the account secret and data secret if they do not already
        exist
        '''

        await self.create_account_secret(accounts_ca)
        await self.create_data_secret(accounts_ca)

    async def create_account_secret(self,
                                    accounts_ca: NetworkAccountsCaSecret
                                    = None):
        '''
        Creates the TLS secret for an account. TODO: create Let's Encrypt
        cert
        '''

        if not self.tls_secret:
            self.tls_secret = AccountSecret(
                self.account, self.account_id, self.network
            )

        if not await self.tls_secret.cert_file_exists():
            _LOGGER.info(
                f'Creating account secret {self.tls_secret.cert_file}'
            )
            self.tls_secret = await self._create_secret(
                AccountSecret, accounts_ca
            )

    async def create_data_secret(self,
                                 accounts_ca: NetworkAccountsCaSecret = None):
        '''
        Creates the PKI secret used to protect all data in the document store
        '''

        if not self.data_secret:
            self.data_secret = AccountDataSecret(
                self.account, self.account_id, self.network
            )

        if (not await self.data_secret.cert_file_exists()
                or not self.data_secret.cert):
            _LOGGER.info(
                f'Creating account data secret {self.data_secret.cert_file}'
            )
            self.data_secret = await self._create_secret(
                AccountDataSecret, accounts_ca
            )

    async def _create_secret(self, secret_cls: Callable, issuing_ca: Secret
                             ) -> Secret:
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

        secret = secret_cls(
            self.account, self.account_id, network=self.network
        )

        if await secret.cert_file_exists():
            raise ValueError(
                f'Cert for {type(secret)} for account_id {self.account_id} '
                'already exists'
            )

        if await secret.private_key_file_exists():
            raise ValueError(
                f'Private key for {type(secret)} for account_id '
                f'{self.account_id} already exists'
            )

        if not issuing_ca:
            if secret_cls != AccountSecret and secret_cls != AccountDataSecret:
                raise ValueError(
                    f'No issuing_ca was provided for creating a '
                    f'{type(secret_cls)}'
                )
            else:
                csr = secret.create_csr(self.account_id)
                payload = {'csr': secret.csr_as_pem(csr).decode('utf-8')}
                url = self.paths.get(Paths.NETWORKACCOUNT_API)

                # TODO: Refactor to use RestClientApi
                _LOGGER.debug(f'Getting CSR signed from {url}')
                resp = requests.post(url, json=payload)
                if resp.status_code != 201:
                    raise RuntimeError('Certificate signing request failed')

                cert_data = resp.json()
                secret.from_string(
                    cert_data['signed_cert'], certchain=cert_data['cert_chain']
                )
        else:
            csr = secret.create_csr()
            issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
            certchain = issuing_ca.sign_csr(csr)
            secret.from_signed_cert(certchain)

        await secret.save(password=self.private_key_password)

        return secret

    async def load_secrets(self):
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

    def create_jwt(self, expiration_days: int = 365) -> JWT:
        '''
        Creates a JWT for the account owning the POD. This JWT can be
        used to authenticate only against the pod.
        '''

        jwt = JWT.create(
            self.account_id, IdType.ACCOUNT, self.tls_secret,
            self.network.name, expiration_days=expiration_days
        )
        return jwt

    async def register(self):
        '''
        Register the pod with the directory server of the network
        '''

        # Register pod to directory server
        url = self.paths.get(Paths.NETWORKACCOUNT_API)

        resp = RestApiClient.call(url, HttpMethod.PUT, self.tls_secret)

        _LOGGER.debug(
            f'Registered account with directory server: {resp.status_code}'
        )

    async def get_memberships(self) -> Set:
        '''
        Get a list of the service_ids that the pod has joined by looking
        at storage.
        '''

        memberships_dir = self.paths.get(self.paths.ACCOUNT_DIR)
        folders = await self.document_store.get_folders(
            memberships_dir, prefix='service-'
        )

        service_ids = set()
        for folder in folders:
            # The folder name starts with 'service-'
            service_id = int(folder[8:])
            service_ids.add(service_id)

        return service_ids

    async def load_memberships(self):
        '''
        Loads the memberships of an account by iterating through
        a directory structure in the document store of the server.
        '''

        _LOGGER.debug('Loading memberships')

        service_ids = await self.get_memberships()

        for service_id in service_ids or []:
            if service_id not in self.memberships:
                await self.load_membership(service_id)

    async def load_membership(self, service_id: int) -> Member:
        '''
        Load the data for a membership of a service
        '''

        _LOGGER.debug(f'Loading membership for service_id: {service_id}')
        if service_id in self.memberships:
            raise ValueError(
                f'Already a member of service {service_id}'
            )

        member = Member(service_id, self)
        await member.setup()

        await member.load_secrets()
        member.data = MemberData(
            member, member.paths, member.document_store
        )

        if member.member_id not in self.memberships:
            member.create_nginx_config()

        member.data.load_protected_shared_key()
        await member.load_data()

        self.memberships[service_id] = member

    async def join(self, service_id: int, schema_version: int,
                   members_ca: MembersCaSecret = None, member_id: UUID = None,
                   local_service_contract: str = None
                   ) -> Member:
        '''
        Join a service for the first time

        :param service_id: The ID of the service to join
        :param schema_version: the version of the schema that has been accepted
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

        member = await Member.create(
            service, schema_version, self, member_id=member_id,
            members_ca=members_ca,
            local_service_contract=local_service_contract
        )

        self.memberships[member.service_id] = member

        return member
