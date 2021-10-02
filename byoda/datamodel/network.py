'''
Class for modeling a social network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import logging
from uuid import UUID

from byoda.util import Paths
from byoda import config

from byoda.datatypes import ServerRole
from byoda.datatypes import CsrSource


from .service import Service
from .account import Account

from byoda.storage.filestorage import FileStorage

from byoda.util.secrets import Secret
from byoda.util.secrets import NetworkRootCaSecret
from byoda.util.secrets import NetworkDataSecret
from byoda.util.secrets import NetworkAccountsCaSecret
from byoda.util.secrets import NetworkServicesCaSecret
from byoda.util.secrets import ServiceCaSecret
from byoda.util.secrets import MembersCaSecret
from byoda.util.secrets import ServiceSecret

from typing import Callable

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

    def __init__(self, server: dict, application: dict,
                 root_ca: NetworkRootCaSecret = None):
        '''
        Set up the network

        :param server: section from config.yml with key 'dirserver',
        'podserver' etc, with keys 'roles', 'private_key_password' and
        parameters specific to the role. A directory server must have key
        'dnsdb'
        :param application: section from config.yml with keys 'network' and
        'root_dir'
        :returns:
        :raises: ValueError, KeyError
        '''

        # TODO: continue reducing the length of this constructor

        self.name = application.get('network', config.DEFAULT_NETWORK)

        self.dnsdb = None

        roles = server.get('roles', [])
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

        if ServerRole.Pod in self.roles:
            bucket_prefix = server['bucket_prefix']
            account = 'pod'
        else:
            bucket_prefix = None
            account = None

        # FileStorage.get_storage ignores bucket_prefix parameter
        # when local storage is used.
        private_object_storage = FileStorage.get_storage(
            server.get('cloud', 'LOCAL'), bucket_prefix, self.root_dir
        )

        self.paths = Paths(
            root_directory=self.root_dir, network=self.name,
            account=account, storage_driver=private_object_storage
        )

        # Everyone must at least have the root ca cert.
        if root_ca:
            self.root_ca = root_ca
        else:
            self.root_ca = NetworkRootCaSecret(self.paths)

        self.data_secret = NetworkDataSecret(self.paths)

        if ServerRole.RootCa in self.roles:
            self.root_ca.load(
                with_private_key=True, password=self.private_key_password
            )
            self.data_secret.load(
                with_private_key=True, password=self.private_key_password
            )
        else:
            if not self.root_ca.cert:
                self.root_ca.load(with_private_key=False)

        config.requests.verify = self.root_ca.cert_file

        # Loading secrets for when operating as a directory server
        self.accounts_ca = None
        self.services_ca = None
        self.services = dict()

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
            self.member_ca = MembersCaSecret(
                None, server['service_id'], self
            )
            self.member_ca.load(
                with_private_key=True,
                password=self.private_key_password
            )

            self.service_secret = ServiceSecret(
                server['service'], server['service_id'], self.paths
            )
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
        self.account_id = None
        self.account_secret = None
        self.member_secrets = set()
        self.services = dict()
        self.account = None
        if ServerRole.Pod in self.roles:
            # TODO: client should read this from a directory server API
            self.load_services(directory='services/')

    @staticmethod
    def create(network_name, root_dir, password):
        '''
        Factory for creating a new Byoda network and its secrets.

        Create the secrets for a network, unless they already exist:
        - Network Root CA
        - Accounts CA
        - Services CA
        - Network Data secret (for sending signed messages)

        A network directory server does not need a TLS secret signed
        by its CA chain as it uses a Let's Encrypt TLS certificate.

        :returns: Network insance
        :raises: ValueError, PermissionError
        '''

        paths = Paths(network=network_name, root_directory=root_dir)

        if not paths.network_directory_exists():
            paths.create_network_directory()

        if not paths.secrets_directory_exists():
            paths.create_secrets_directory()

        # Create root CA
        root_ca = NetworkRootCaSecret(paths=paths)

        if root_ca.cert_file_exists():
            root_ca.load(password=password)
        else:
            root_ca.create(expire=100*365)
            root_ca.save(password=password)

        network_data = {
            'network': network_name, 'root_dir': root_dir,
            'private_key_password': password
        }
        network = Network(network_data, network_data, root_ca)

        # Root CA, signs Accounts CA, Services CA and
        # Network Data Secret. We don't need a 'Network.ServiceSecret'
        # as we use the Let's Encrypt cert for TLS termination
        network.data_secret = Network._create_secret(
            network.name, NetworkDataSecret, root_ca, paths, password
        )

        network.accounts_ca = Network._create_secret(
            network.name, NetworkAccountsCaSecret, root_ca, paths, password
        )

        network.services_ca = Network._create_secret(
            network.name, NetworkServicesCaSecret, root_ca, paths, password
        )

        return network

    @staticmethod
    def _create_secret(network: str, secret_cls: Callable, issuing_ca: Secret,
                       paths: Paths, password: str):
        '''
        Abstraction helper for creating secrets for a Network to avoid
        repetition of code for creating the various member secrets of the
        Network class

        :param secret_cls: callable for one of the classes derived from
        byoda.util.secrets.Secret
        :raises: ValueError
        '''

        if not network:
            raise ValueError(
                'Name and service_id of the service have not been defined'
            )

        if not issuing_ca:
            raise ValueError(
                f'No issuing_ca was provided for creating a '
                f'{type(secret_cls)}'
            )

        secret = secret_cls(paths=paths)

        if secret.cert_file_exists():
            secret.load(password=password)
            return secret

        csr = secret.create_csr()
        issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
        certchain = issuing_ca.sign_csr(csr)
        secret.from_signed_cert(certchain)
        secret.save(password=password)

        return secret

    def load_services(self, directory: str = None) -> None:
        '''
        Load a list of all the services in the network.
        '''

        if self.services:
            _LOGGER.debug('Reloading list of services')
            self.services = dict()

        for root, __dirnames, files in os.walk(directory):
            for filename in [x for x in files if x.endswith('.json')]:
                service = Service.get_service(
                    self, filepath=os.path.join(root, filename)
                )

                if service.service_id in self.services:
                    raise ValueError(
                        f'Duplicate service_id: {service.service_id}'
                    )

                self.services[service.service_id] = service

    def load_secrets(self) -> None:
        '''
        Loads the secrets of the network, except for the root CA
        '''

        self.accounts_ca = NetworkAccountsCaSecret(self.paths)
        self.accounts_ca.load(
            with_private_key=True, password=self.private_key_password
        )
        self.services_ca = NetworkServicesCaSecret(self.paths)
        self.services_ca.load(
            with_private_key=True, password=self.private_key_password
        )
        self.data_secret = NetworkDataSecret(self.paths)
        self.data_secret.load(
            with_private_key=True, password=self.private_key_password
        )

    def load_account(self, account_id: UUID, load_tls_secret: bool = True
                     ) -> Account:
        '''
        Loads an account and its secrets
        '''

        account = Account(account_id, self, load_tls_secret=load_tls_secret)

        return account
