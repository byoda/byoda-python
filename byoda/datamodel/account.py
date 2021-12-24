'''
Class for modeling an account on a network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID
from typing import TypeVar, Callable, Dict
from copy import copy
from uuid import uuid4

import requests

from byoda.datatypes import CsrSource
from byoda.datastore import DocumentStore
from byoda.datamodel import Schema
from byoda.datamodel import MemberData

from byoda.secrets import Secret
from byoda.secrets import AccountSecret
from byoda.secrets import DataSecret
from byoda.secrets import AccountDataSecret
from byoda.secrets import NetworkAccountsCaSecret
from byoda.secrets import MembersCaSecret

from byoda.util import Paths
from byoda.util.api_client import RestApiClient
from byoda.util.api_client.restapi_client import HttpMethod

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
                 account: str = 'pod', bootstrap: bool = False):
        '''
        Constructor
        '''

        self.account: str = account

        if isinstance(account_id, UUID):
            self.account_id: UUID = account_id
        else:
            try:
                self.account_id: UUID = UUID(account_id)
            except ValueError:
                raise (f'AccountID {account_id} is not a valid UUID')

        self.document_store: DocumentStore = None
        if hasattr(config.server, 'document_store'):
            self.document_store = config.server.document_store

        self.memberships: Dict[int, Member] = dict()

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
        self.paths.create_account_directory()

        self.load_memberships(bootstrap=bootstrap)

    def create_secrets(self, accounts_ca: NetworkAccountsCaSecret = None):
        '''
        Creates the account secret and data secret if they do not already
        exist
        '''

        self.create_account_secret(accounts_ca)
        self.create_data_secret(accounts_ca)

    def create_account_secret(self,
                              accounts_ca: NetworkAccountsCaSecret = None):
        '''
        Creates the TLS secret for an account. TODO: create Let's Encrypt
        cert
        '''

        if not self.tls_secret:
            self.tls_secret = AccountSecret(
                self.account, self.account_id, self.network
            )

        if not self.tls_secret.cert_file_exists():
            _LOGGER.info('Creating account secret')
            self.tls_secret = self._create_secret(
                AccountSecret, accounts_ca
            )

    def create_data_secret(self, accounts_ca: NetworkAccountsCaSecret = None):
        '''
        Creates the PKI secret used to protect all data in the document store
        '''

        if not self.data_secret:
            self.data_secret = AccountDataSecret(
                self.account, self.account_id, self.network
            )

        if (not self.data_secret.cert_file_exists()
                or not self.data_secret.cert):
            _LOGGER.info('Creating account data secret')
            self.data_secret = self._create_secret(
                AccountDataSecret, accounts_ca
            )

    def _create_secret(self, secret_cls: Callable, issuing_ca: Secret
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

        if secret.cert_file_exists():
            raise ValueError(
                f'Cert for {type(secret)} for account_id {self.account_id} '
                'already exists'
            )

        if secret.private_key_file_exists():
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

        secret.save(password=self.private_key_password)

        return secret

    def load_secrets(self):
        '''
        Loads the secrets for the account
        '''

        self.tls_secret = AccountSecret(
            self.account, self.account_id, self.network
        )
        self.tls_secret.load(password=self.private_key_password)
        self.data_secret = AccountDataSecret(
            self.account, self.account_id, self.network
        )
        self.data_secret.load(password=self.private_key_password)

    def load_memberships(self, bootstrap: bool = False):
        '''
        Loads the memberships of an account by iterating through
        a directory structure in the document store of the server.
        '''

        memberships_dir = self.paths.get(self.paths.ACCOUNT_DIR)
        folders = self.document_store.get_folders(
            memberships_dir, prefix='service-'
        )

        for folder in folders:
            # The fo
            service_id = int(folder[8:])
            self.load_membership(service_id=service_id, bootstrap=bootstrap)

    def load_membership(self, service_id: int,
                        bootstrap: bool = False) -> Member:
        '''
        Load the data for a membership of a service
        '''

        if service_id in self.memberships:
            raise ValueError(
                f'Already a member of service {service_id}'
            )

        try:
            member = Member(service_id, self)
            member.load_secrets()
            member.data = MemberData(
                member, member.paths, member.document_store
            )
            member.data.load_protected_shared_key()
            member.create_nginx_config()
        except FileNotFoundError:
            if bootstrap:
                if not member.tls_secret or not member.data_secret:
                    if not member.member_id:
                        member.member_id = uuid4()

                    member.create_secrets()

                if not member.paths._exists(member.paths.SERVICE_FILE):
                    filepath = member.paths.get(
                        member.paths.SERVICE_FILE
                    )
                    member.service.download_schema(
                        save=True, filepath=filepath
                    )
                    member.schema = Schema.get_schema(
                        filepath, member.storage_driver,
                        member.service.data_secret,
                        self.network.data_secret
                    )

                filepath = member.paths.get(
                    member.paths.MEMBER_DATA_SHARED_SECRET_FILE
                )

                if not member.paths._exists(filepath):
                    member.data_secret.create_shared_key()

                if not member.data:
                    member.data = MemberData(
                        member, member.paths, member.document_store
                    )
                    member.data.save_protected_shared_key()

        member.load_data()

        self.memberships[service_id] = member

    def register(self):
        '''
        Register the pod with the directory server of the network
        '''

        # Register pod to directory server
        url = self.paths.get(Paths.NETWORKACCOUNT_API)

        resp = RestApiClient.call(url, HttpMethod.PUT, self.tls_secret)

        _LOGGER.debug(
            f'Registered account with directory server: {resp.status_code}'
        )

    def join(self, service: Service = None, service_id: int = None,
             schema_version: int = None, members_ca: MembersCaSecret = None
             ) -> Member:
        '''
        Join a service for the first time
        '''

        if ((service_id is None and not service)
                or (service_id and service)):
            raise ValueError('Either service_id or service must be speicfied')

        if service and not isinstance(service, Service):
            raise ValueError(
                f'service must be of instance Service and not {type(Service)}'
            )

        if service_id is not None:
            service_id = int(service_id)
            service = Service(service_id=service_id, network=self.network)

        if not self.paths.member_directory_exists(service.service_id):
            self.paths.create_member_directory(service.service_id)

        member = Member.create(service, schema_version, self, members_ca)

        self.memberships[member.member_id] = member

        return member
