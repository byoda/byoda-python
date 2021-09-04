'''
Class for modeling an account on a network

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID
from typing import TypeVar, Callable
from copy import copy

import requests

from byoda.datatypes import CsrSource

from .member import Member
from .service import Service

from byoda.util.secrets import Secret
from byoda.util.secrets import AccountSecret
from byoda.util.secrets import AccountDataSecret
from byoda.util.secrets import NetworkAccountsCaSecret
from byoda.util.secrets import MembersCaSecret

from byoda import config

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class Account:
    '''
    Class for modelling an account.

    This class is expected to only be used in the podserver
    '''

    def __init__(self,  account_id: str, network: Network,
                 load_tls_secret=False, account='pod'):
        '''
        Constructor
        '''

        self.account = account

        if isinstance(account_id, UUID):
            self.account_id = account_id
        else:
            try:
                self.account_id = UUID(account_id)
            except ValueError:
                raise (f'AccountID {account_id} is not a valid UUID')

        self.document_store = None
        if hasattr(config.server, 'document_store'):
            self.document_store = config.server.document_store

        self.memberships = dict()

        self.network = network

        self.private_key_password = network.private_key_password

        self.tls_secret = None
        self.data_secret = None
        self.tls_secret = AccountSecret(
            self.account, self.account_id, self.network
        )
        if load_tls_secret:
            self.tls_secret.load(password=self.private_key_password)

        self.paths = copy(network.paths)
        self.paths.account = self.account
        self.paths.account_id = self.account_id
        self.paths.create_account_directory()

        self.load_memberships()

    def create_secrets(self, accounts_ca: NetworkAccountsCaSecret = None):
        '''
        Creates the account secret and data secret if they do not already
        exist
        '''
        self.create_account_secret(accounts_ca)
        self.create_data_secret(accounts_ca)

    def create_account_secret(self,
                              accounts_ca: NetworkAccountsCaSecret = None):
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
        if not self.data_secret:
            self.data_secret = AccountDataSecret(
                self.account, self.account_id, self.network
            )

        if not self.data_secret.cert_file_exists():
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
            # TODO
            if type(secret_cls) != AccountSecret:
                raise ValueError(
                    f'No issuing_ca was provided for creating a '
                    f'{type(secret_cls)}'
                )
            else:
                csr = secret.create_csr(self.account_id)
                payload = {'csr': secret.csr_as_pem(csr).decode('utf-8')}
                url = f'https://dir.{self.network}/api/v1/network/account'

                resp = requests.post(url, json=payload)
                if resp.status_code != requests.codes.OK:
                    raise RuntimeError('Certificate signing request failed')

                cert_data = resp.json()
                secret.from_string(
                    cert_data['signed_cert'], certchain=cert_data['cert_chain']
                )
        else:
            csr = secret.create_csr()
            issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
            certchain = issuing_ca.sign_csr(csr)
            secret.add_signed_cert(certchain)

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

    def load_memberships(self):
        memberships_dir = self.paths.get(self.paths.ACCOUNT_DIR)
        folders = self.document_store.get_folders(
            memberships_dir, prefix='service-'
        )

        for folder in folders:
            service_id = int(folder[8:])
            self.load_membership(service_id=service_id)

    def load_membership(self, service_id: int) -> Member:
        '''
        Load the data for a membership of a service
        '''

        if service_id in self.memberships:
            raise ValueError(
                f'Already a member of service {service_id}'
            )

        member = Member(service_id, self)
        member.load_data()
        member.load_secrets()

        self.memberships[service_id] = member

    def join(self, service: Service = None, service_id: int = None,
             members_ca: MembersCaSecret = None) -> Member:
        '''
        Join a service for the first time
        '''

        if ((not service_id and not service)
                or (service_id and service)):
            raise ValueError('Either service_id or service must be speicfied')

        if service and not isinstance(service, Service):
            raise ValueError(
                f'service must be of instance Service and not {type(Service)}'
            )

        if service_id:
            service_id = int(service_id)
            service = Service(service_d=service_id, network=self.network)

        if not self.paths.member_directory_exists(service.service_id):
            self.paths.create_member_directory(service.service_id)

        member = Member.create(service, self, members_ca)

        self.memberships[member.member_id] = member

        return member
