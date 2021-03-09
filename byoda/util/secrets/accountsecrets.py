'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from byoda.util import Paths

from . import Secret, CsrSource

_LOGGER = logging.getLogger(__name__)


class AccountSecret(Secret):
    def __init__(self, paths):
        '''
        Class for the network Account secret

        :param Paths paths: instance of Paths class defining the directory
                            structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        super().__init__(
            cert_file=paths.get(Paths.ACCOUNT_CERT_FILE),
            key_file=paths.get(Paths.ACCOUNT_KEY_FILE),
        )

        self.account_id = None
        self.account_alias = paths.account
        self.network = paths.network
        self.ca = False

    def create(self):
        raise NotImplementedError

    def create_csr(self, account_id):
        '''
        Creates an RSA private key and X.509 CSR

        :param uuid4 account_id: account_id
        :returns: csr
        :raises: ValueError if the Secret instance already has a private key
                 or cert
        '''

        self.account_id = account_id
        common_name = f'{self.account_id}.account.{self.network}'

        return super().create_csr(common_name, ca=self.ca)

    def review_csr(self):
        raise NotImplementedError


class MemberSecret(Secret):
    def __init__(self, service_alias, paths):
        '''
        Class for the member secret of an account for a service

        :param Paths paths: instance of Paths class defining the directory
                            structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        super().__init__(
            cert_file=paths.get(
                Paths.MEMBER_CERT_FILE, service_alias=service_alias
            ),
            key_file=paths.get(
                Paths.MEMBER_KEY_FILE, service_alias=service_alias
            )
        )
        self.ca = False

    def create_csr(self, network, service_id, member_id, expire=3650):
        '''
        Creates an RSA private key and X.509 CSR

        :param int service_id: identifier for the service
        :param uuid member_id: identifier of the member for the service
        :param int expire: days after which the cert should expire
        :returns: csr
        :raises: ValueError if the Secret instance already has
                                a private key or cert
        '''

        self.member_id = member_id
        common_name = f'{member_id}-{service_id}.member.{network}'

        return super().create_csr(common_name, ca=self.ca)

    def review_csr(self, csr, source=CsrSource.WEBAPI):
        raise NotImplementedError


class DataSecret(Secret):
    def __init__(self, paths):
        '''
        Class for the data secret for a pod

        :param Paths paths: instance of Paths class defining the directory
                            structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        super().__init__(
            cert_file=paths.get(Paths.DATA_CERT_FILE),
            key_file=paths.get(Paths.DATA_KEY_FILE)
        )
        self.ca = False

    def create(self, expire=36500):
        '''
        Creates an RSA private key and X.509 cert

        :param int expire: days after which the cert should expire
        :returns: (none)
        :raises: ValueError if the Secret instance already has a private key
                 or cert

        '''

        common_name = f'data-{self.account}'
        super().create(common_name, expire=expire, key_size=4096, ca=self.ca)

    def create_csr(self, expire=3650):
        raise NotImplementedError

    def review_csr(self, csr, source=CsrSource.WEBAPI):
        raise NotImplementedError
