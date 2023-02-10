'''
Class for modeling an account on a network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
from uuid import UUID
from typing import TypeVar
from copy import copy

from byoda.datatypes import CsrSource
from byoda.datatypes import IdType
from byoda.datatypes import MemberStatus

from byoda.datastore.document_store import DocumentStore
from byoda.datastore.data_store import DataStore

from byoda.datamodel.memberdata import MemberData

from byoda.secrets import Secret
from byoda.secrets import AccountSecret
from byoda.secrets import DataSecret
from byoda.secrets import AccountDataSecret
from byoda.secrets import NetworkAccountsCaSecret
from byoda.secrets import MembersCaSecret

from byoda.util.paths import Paths
from byoda.util.reload import reload_gunicorn
from byoda.util.api_client.restapi_client import RestApiClient
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

    async def create_secrets(self, accounts_ca: NetworkAccountsCaSecret = None,
                             renew: bool = False):
        '''
        Creates the account secret and data secret if they do not already
        exist
        '''

        await self.create_account_secret(accounts_ca, renew=renew)
        await self.create_data_secret(accounts_ca, renew=renew)

    async def create_account_secret(self,
                                    accounts_ca: NetworkAccountsCaSecret
                                    = None, renew: bool = False):
        '''
        Creates the TLS secret for an account. TODO: create Let's Encrypt
        cert
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

    async def create_data_secret(self,
                                 accounts_ca: NetworkAccountsCaSecret = None,
                                 renew: bool = False):
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
                payload = {'csr': secret.csr_as_pem(csr).decode('utf-8')}
                url = self.paths.get(Paths.NETWORKACCOUNT_API)

                _LOGGER.debug(f'Getting CSR signed from {url}')
                resp = await RestApiClient.call(
                    url, method=HttpMethod.POST, data=payload
                )
                if resp.status != 201:
                    raise RuntimeError('Certificate signing request failed')

                cert_data = await resp.json()
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

        resp = await RestApiClient.call(url, HttpMethod.PUT, self.tls_secret)

        _LOGGER.debug(
            f'Registered account with directory server: {resp.status}'
        )

    async def load_memberships(self) -> None:
        '''
        Loads the memberships of an account
        '''

        _LOGGER.debug('Loading memberships')

        memberships = await self.get_memberships()

        for membership in memberships.values() or {}:
            member_id: UUID = membership['member_id']
            service_id: int = membership['service_id']
            if service_id not in self.memberships:
                _LOGGER.debug(
                    f'Loading membership for service {service_id}: {member_id}'
                )
                await self.load_membership(service_id, member_id)

    async def get_memberships(self, status: MemberStatus = MemberStatus.ACTIVE
                              ) -> dict[UUID, dict[
                                  str, UUID | str | MemberStatus | float]]:
        '''
        Get a list of the service_ids that the pod has joined by looking
        at storage.

        :returns: dict of membership UUID with as value a dict with keys
        member_id, service_id, status, timestamp,
        '''

        data_store: DataStore = config.server.data_store
        memberships = await data_store.backend.get_memberships(status)
        _LOGGER.debug(
            f'Got {len(memberships)} memberships with '
            f'status {status} from account DB'
        )

        return memberships

    async def load_membership(self, service_id: int, member_id: UUID
                              ) -> Member:
        '''
        Load the data for a membership of a service
        '''

        _LOGGER.debug(f'Loading membership for service_id: {service_id}')
        if service_id in self.memberships:
            raise ValueError(
                f'Already a member of service {service_id}'
            )

        member = Member(service_id, self, member_id=member_id)

        await member.setup(new_membership=False)

        data_store: DataStore = config.server.data_store
        await data_store.backend.setup_member_db(
                member.member_id, member.service_id, member.schema
        )

        await member.load_secrets()
        member.data = MemberData(member)

        if service_id not in self.memberships:
            await member.load_service_cacert()
            await member.create_nginx_config()

        await member.data.load_protected_shared_key()

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

        await member.load_service_cacert()

        await member.create_nginx_config()
        reload_gunicorn()

        self.memberships[service_id] = member

        return member
