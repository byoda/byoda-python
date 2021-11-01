'''
Class for modeling a social network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import logging
from uuid import UUID
from typing import Dict, Set
from typing import Callable

import passgen

from byoda.util import Paths
from byoda import config

from byoda.datatypes import ServerRole
from byoda.datatypes import CsrSource

from byoda.datamodel.service import RegistrationStatus

from byoda.storage.filestorage import FileStorage

from byoda.secrets import Secret
from byoda.secrets import DataSecret
from byoda.secrets import NetworkRootCaSecret
from byoda.secrets import NetworkDataSecret
from byoda.secrets import NetworkAccountsCaSecret
from byoda.secrets import NetworkServicesCaSecret
from byoda.secrets import ServiceCaSecret
from byoda.secrets import MembersCaSecret
from byoda.secrets import ServiceSecret

from .service import Service
from .account import Account


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

    # Limit for restricted services
    MAX_RESTRICTED_SERVICE_ID = 65535
    # Pods should only accept test service IDs when running in DEBUG mode
    MIN_TEST_SERVICE_ID = 4293918720

    def __init__(self, server: dict, application: dict,
                 root_ca: NetworkRootCaSecret = None):
        '''
        Set up the network

        :param server: section from config.yml with key 'dirserver',
        'svcserver', 'podserver' etc, with keys 'roles', 'root_dir'
        'private_key_password', 'logfile' and parameters specific to the
        role. A directory server must have key 'dnsdb'
        :param application: section from config.yml with keys 'network',
        'debug', 'environment'
        :returns:
        :raises: ValueError, KeyError
        '''

        # TODO: continue reducing the length of this constructor

        self.name: str = application.get('network', config.DEFAULT_NETWORK)

        self.dnsdb = None

        roles: Set[str] = server.get('roles', [])
        if roles and type(roles) not in (set, list):
            roles = [roles]

        self.roles: Set = set()
        for role in roles:
            try:
                role_type = ServerRole(role)
                self.roles.add(role_type)
            except ValueError:
                raise ValueError(f'Invalid role {role}')

        self.root_dir: str = server.get(
            'root_dir', os.environ['HOME'] + '.byoda'
        )

        self.private_key_password: str = server['private_key_password']

        if ServerRole.Pod in self.roles:
            bucket_prefix: str = server['bucket_prefix']
            account: str = 'pod'
        else:
            bucket_prefix = None
            account = None

        # FileStorage.get_storage ignores bucket_prefix parameter
        # when local storage is used.
        private_object_storage: FileStorage = FileStorage.get_storage(
            server.get('cloud', 'LOCAL'), bucket_prefix, self.root_dir
        )

        self.paths: Paths = Paths(
            root_directory=self.root_dir, network=self.name,
            account=account, storage_driver=private_object_storage
        )

        # Everyone must at least have the root ca cert.
        self.root_ca: NetworkRootCaSecret = None
        if root_ca:
            self.root_ca: NetworkRootCaSecret = root_ca
        else:
            self.root_ca = NetworkRootCaSecret(self.paths)

        self.data_secret: NetworkDataSecret = NetworkDataSecret(self.paths)

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
        self.accounts_ca: NetworkAccountsCaSecret = None
        self.services_ca: NetworkServicesCaSecret = None
        self.tls_secret: Secret = None
        self.data_secret: DataSecret = None

        self.services: Dict[int: Service] = dict()

        # Secrets for a service must be loaded using SvcServer.load_secrets()
        self.services_ca: ServiceCaSecret = None
        self.service_secret: ServiceSecret = None
        self.member_ca: MembersCaSecret = None

        # Loading secrets when operating as a pod
        self.account_id = None
        self.account_secret = None
        self.member_secrets = set()
        self.services = dict()
        self.account = None

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
            root_ca.load(with_private_key=True, password=password)
        else:
            root_ca.create(expire=100*365)
            root_ca_password = passgen.passgen(length=48)
            root_ca.save(password=root_ca_password)
            _LOGGER.info(
                f'!!! Saving root CA using password {root_ca_password}'
            )

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

        # Create the services directory to enable the directory server to start
        os.mkdir(paths.get(Paths.SERVICES_DIR))

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

        # TODO: SECURITY: add constraints
        csr = secret.create_csr()
        issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
        certchain = issuing_ca.sign_csr(csr)
        secret.from_signed_cert(certchain)
        secret.save(password=password)

        return secret

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

    def add_service(self, service_id: int,
                    registration_status: RegistrationStatus = None) -> Service:
        '''
        Adds a service to the in-memory list of known services. No exception
        will be thrown if the service is already known
        '''

        if service_id in self.services:
            _LOGGER.debug(f'Service {service_id} is already in memory')
            service = self.services[service_id]
        else:
            service = Service(self, service_id=service_id)
            self.services[service_id] = service

        if (registration_status and
                registration_status != RegistrationStatus.Unknown):
            _LOGGER.debug(
                f'Setting service {service_id} to status '
                f'{registration_status}'
            )
            service.registration_status = \
                registration_status
        else:
            service.registration_status = service.get_registration_status()

        return service
