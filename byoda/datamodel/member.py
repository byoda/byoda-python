'''
Class for modeling an account on a network

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from uuid import uuid4
from copy import copy
from typing import TypeVar, Callable

from byoda.datatypes import CsrSource

from byoda.datamodel.service import Service
from byoda.util.secrets import MemberSecret, MemberDataSecret
from byoda.util.secrets import Secret, MembersCaSecret


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

        self.paths = copy(self.network.paths)

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
        member.data_secter = member._create_secret(
            MemberDataSecret, members_ca
        )

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

        self.tls_secret = MemberSecret(self.service_id, self.paths)
        self.tls_secret.load(
            with_private_key=True, password=self.private_key_password
        )

        self.data_secret = MemberDataSecret(self.service_id, self.paths)
        self.data_secret.load(
            with_private_key=True, password=self.private_key_password
        )

    def load_data(self):
        '''
        Loads the data stored for the membership
        '''

        try:
            data = self.account.document_store.read(
                self.paths.get(
                    self.paths.MEMBER_DATA_FILE, service_id=self.service_id
                )
            )
            self.service.validate(data)
        except OSError:
            _LOGGER.error(
                f'Unable to read data file for service {self.service_id}'
            )
            data = None

        return data
