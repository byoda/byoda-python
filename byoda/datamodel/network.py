'''
Class for modeling a social network

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import logging

from byoda.util import Paths
from byoda.util import config

from byoda.datatypes import ServerRole

from byoda.datastore import DnsDb

from byoda.util.secrets import NetworkRootCaSecret
from byoda.util.secrets import NetworkAccountsCaSecret
from byoda.util.secrets import NetworkServicesCaSecret
from byoda.util.secrets import ServiceCaSecret
from byoda.util.secrets import MembersCaSecret
from byoda.util.secrets import ServiceSecret
from byoda.util.secrets import AccountSecret
from byoda.util.secrets import MemberSecret


_LOGGER = logging.getLogger(__name__)


class Network:
    '''
    A BYODA social network

    It supports the following use cases:
    - An off-line server with access to the private key of the network
    signing CSRs of issuing CAs for accounts and services. I
    - A server acting as issuing CA, receiving API requests for signing
    account certs and service certs. It has access to its own public and
    private key and the public key of the network CA. This server also
    has access to the TLS server cert and key supplied by Let's Encrypt
    - A client or service submitting a CSR or registering themselves to the
    network. It has access to its own cert and private key and the public
    key of the network.
    '''

    def __init__(self, server, application):
        self.name = server['name']
        self.network = application['network']
        self.dnsdb = None

        roles = server['roles']
        if roles and type(roles) not in (set, list):
            roles = [roles]

        self.roles = set()
        for role in roles:
            try:
                role_type = ServerRole(role)
                self.roles.add(role_type)
            except ValueError:
                raise ValueError(f'Invalid role {role}')

        self.root_dir = application.get(
            'root_dir', os.environ['HOME'] + '.byoda'
        )

        self.private_key_password = server['private_key_password']

        self.paths = Paths(self.root_dir, network_name=application['network'])

        # Everyone must at least have the root ca cert.
        self.root_ca = NetworkRootCaSecret(self.paths)
        if ServerRole.RootCa in self.roles:
            self.root_ca.load(
                with_private_key=True, password=self.private_key_password
            )
        else:
            self.root_ca.load(with_private_key=False)

        config.requests.verify = self.root_ca.cert_file

        # Loading secrets for when operating as a directory server
        self.accounts_ca = None
        self.services_ca = None
        if ServerRole.DirectoryServer in self.roles:
            self.accounts_ca = NetworkAccountsCaSecret(self.paths)
            self.accounts_ca.load(
                with_private_key=True, password=self.private_key_password
            )
            self.services_ca = NetworkServicesCaSecret(self.paths)
            self.services_ca.load(
                with_private_key=True, password=self.private_key_password
            )

            self.dnsdb = DnsDb.setup(server['dnsdb'], self.network)

        self.service_ca = None
        if ServerRole.ServiceCa in self.roles:
            self.service_ca = ServiceCaSecret(server['service'], self.paths)
            self.service_ca.load(
                with_private_key=True, password=self.private_key_password
            )

        # Loading secrets when operating a service
        self.service_secret = None
        self.member_ca = None
        if ServerRole.ServiceServer in self.roles:
            config.requests.cert = ()
            self.member_ca = MembersCaSecret(server.service, self.paths)
            self.member_ca.load(
                with_private_key=True,
                password=self.private_key_password
            )

            self.service_secret = ServiceSecret(server['service'], self.paths)
            self.service_secret.load(
                with_private_key=True,
                password=self.private_key_password
            )
            self.service_secret.load()

            # We use the service secret as client TLS cert for outbound
            # requests
            filepath = self.service_secret.save_tmp_private_key()
            config.requests.cert = (self.service_secret.cert_file, filepath)

        # Loading secrets when operating as a pod
        self.account = None
        self.account_secret = None
        self.data_secret = None
        self.member_secrets = set()
        if ServerRole.Pod in roles:
            self.account = server.account
            self.paths.account = self.account
            self.account_secret = AccountSecret(self.paths)

            # We use the service secret as client TLS cert for outbound
            # requests
            filepath = self.service_secret.save_tmp_private_key()
            config.requests.cert = (self.service_secret.cert_file, filepath)

            paths = self.paths
            for directory in os.listdir(paths.get(paths.ACCOUNT_DIR)):
                if not directory.startswith('service-'):
                    continue
                service = directory[8:]
                self.member_secrets[service] = MemberSecret(
                    service, self.paths
                )
                self.member_secrets[service].load(
                    with_private_key=True, password=self.private_key_password
                )
