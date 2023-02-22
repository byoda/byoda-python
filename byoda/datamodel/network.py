'''
Class for modeling a social network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os
import logging

import passgen

from byoda.util.paths import Paths
from byoda import config

from byoda.datatypes import ServerRole
from byoda.datatypes import CsrSource

from byoda.datamodel.service import RegistrationStatus

from byoda.storage.filestorage import FileStorage

from byoda.secrets import Secret
from byoda.secrets import NetworkRootCaSecret
from byoda.secrets import NetworkDataSecret
from byoda.secrets import NetworkAccountsCaSecret
from byoda.secrets import NetworkServicesCaSecret
from byoda.secrets import ServiceCaSecret
from byoda.secrets import MembersCaSecret
from byoda.secrets import ServiceSecret

from byoda.util.api_client.api_client import ApiClient

from .service import Service


_LOGGER = logging.getLogger(__name__)


class Network:
    '''
    A BYODA social network

    This class supports the following use cases:
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

    def __init__(self, server: dict, application: dict):
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

        # Loading secrets for when operating as a directory server
        self.accounts_ca: NetworkAccountsCaSecret = None
        self.services_ca: NetworkServicesCaSecret = None
        self.tls_secret: Secret = None

        self.services: dict[int: Service] = dict()
        self.service_summaries: dict[int:dict] = dict()

        # Secrets for a service must be loaded using SvcServer.load_secrets()
        self.services_ca: ServiceCaSecret = None
        self.tls_secret: ServiceSecret = None
        self.member_ca: MembersCaSecret = None

        # Loading secrets when operating as a pod
        self.account_id = None
        self.account_secret = None
        self.member_secrets = set()
        self.services = dict()
        self.account = None

        self.name: str = application.get('network', config.DEFAULT_NETWORK)

        self.dnsdb = None
        self.paths: Paths = None

        roles: set[str] = server.get('roles', [])
        if roles and type(roles) not in (set, list):
            roles = [roles]

        self.roles: set = set()
        for role in roles:
            try:
                role_type = ServerRole(role)
                self.roles.add(role_type)
            except ValueError:
                raise ValueError(f'Invalid role {role}')

        self.root_dir: str = server['root_dir']

        self.private_key_password: str = server['private_key_password']

        if ServerRole.Pod in self.roles:
            self.bucket_prefix: str | None = server['bucket_prefix']
            self.account: str | None = 'pod'
        else:
            self.bucket_prefix: str | None = None
            self.account: str | None = None

        self.cloud: str = server.get('cloud', 'LOCAL')

    @staticmethod
    async def create(network_name: str, root_dir: str, password: str):
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

        if not await paths.network_directory_exists():
            await paths.create_network_directory()

        if not await paths.secrets_directory_exists():
            await paths.create_secrets_directory()

        # Create root CA
        root_ca = NetworkRootCaSecret(paths=paths)

        if await root_ca.cert_file_exists():
            await root_ca.load(with_private_key=True, password=password)
        else:
            await root_ca.create(expire=100*365)
            root_ca_password = passgen.passgen(length=48)
            await root_ca.save(password=root_ca_password)
            _LOGGER.info(
                f'!!! Saving root CA using password {root_ca_password}'
            )

        network_data = {
            'network': network_name, 'root_dir': root_dir,
            'private_key_password': password, 'roles': ['test']
        }
        network = Network(network_data, network_data)
        await network.load_network_secrets(root_ca)

        # Root CA, signs Accounts CA, Services CA and
        # Network Data Secret. We don't need a 'Network.ServiceSecret'
        # as we use the Let's Encrypt cert for TLS termination
        if not network.data_secret or not network.data_secret.cert:
            network.data_secret = await Network._create_secret(
                network.name, NetworkDataSecret, root_ca, paths, password
            )

        network.accounts_ca = await Network._create_secret(
            network.name, NetworkAccountsCaSecret, root_ca, paths, password
        )

        network.services_ca = await Network._create_secret(
            network.name, NetworkServicesCaSecret, root_ca, paths, password
        )

        # Create the services directory to enable the directory server to start
        os.makedirs(
            paths._root_directory + '/' + paths.get(Paths.SERVICES_DIR),
            exist_ok=True
        )

        return network

    @staticmethod
    async def _create_secret(network: str, secret_cls: callable,
                             issuing_ca: Secret, paths: Paths, password: str,
                             renew: bool = False):
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

        if (await secret.cert_file_exists()
                or await secret.private_key_file_exists()):
            if not renew:
                raise ValueError(
                    f'Secret already exists: {secret.cert_file}, '
                    f'{secret.private_key_file}'
                )
            await secret.load(password=password)
            return secret

        # TODO: SECURITY: add constraints
        csr = await secret.create_csr()
        issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
        certchain = issuing_ca.sign_csr(csr)
        secret.from_signed_cert(certchain)
        await secret.save(password=password)

        return secret

    async def load_secrets(self) -> None:
        '''
        Loads the secrets of the network, except for the root CA
        '''

        self.accounts_ca = NetworkAccountsCaSecret(self.paths)
        await self.accounts_ca.load(
            with_private_key=True, password=self.private_key_password
        )
        self.services_ca = NetworkServicesCaSecret(self.paths)
        await self.services_ca.load(
            with_private_key=True, password=self.private_key_password
        )
        self.data_secret = NetworkDataSecret(self.paths)
        await self.data_secret.load(
            with_private_key=True, password=self.private_key_password
        )

    async def load_network_secrets(self, root_ca: NetworkRootCaSecret = None):

        # FileStorage.get_storage ignores bucket_prefix parameter
        # when local storage is used.
        private_object_storage: FileStorage = await FileStorage.get_storage(
            self.cloud, self.bucket_prefix, self.root_dir
        )

        self.paths: Paths = Paths(
            root_directory=self.root_dir, network=self.name,
            account=self.account, storage_driver=private_object_storage
        )

        # Everyone must at least have the root ca cert.
        if root_ca:
            self.root_ca: NetworkRootCaSecret = root_ca
        else:
            self.root_ca = NetworkRootCaSecret(self.paths)

        self.data_secret: NetworkDataSecret = NetworkDataSecret(self.paths)

        if ServerRole.RootCa in self.roles:
            await self.root_ca.load(
                with_private_key=True, password=self.private_key_password
            )
            await self.data_secret.load(
                with_private_key=True, password=self.private_key_password
            )
        elif ServerRole.Test in self.roles:
            # HACK: setting renew to True to avoid exception when secret
            # already exists. As this is for a test case, we don't really care
            self.data_secret = await Network._create_secret(
                self.name, NetworkDataSecret, self.root_ca, self.paths,
                self.private_key_password, renew=True
            )
        else:
            if not self.root_ca.cert:
                try:
                    await self.root_ca.load(with_private_key=False)
                except FileNotFoundError:
                    _LOGGER.debug(
                        'Did not find cert for network root CA, downloading it'
                    )
                    resp = await ApiClient.call(
                        Paths.NETWORK_CERT_DOWNLOAD, network_name=self.name
                    )
                    if resp.status != 200:
                        raise ValueError(
                            'No network cert available locally or from the '
                            'network'
                        )
                    _LOGGER.debug('Downloaded cert for Network root CA')
                    self.root_ca.from_string(await resp.text())

                if self.root_ca.cert:
                    try:
                        await self.root_ca.save()
                    except PermissionError:
                        pass

            if not self.data_secret.cert:
                try:
                    await self.data_secret.load(with_private_key=False)
                except FileNotFoundError:
                    resp = await ApiClient.call(
                        Paths.NETWORK_DATACERT_DOWNLOAD, network_name=self.name
                    )
                    if resp.status != 200:
                        raise ValueError(
                            'No network cert available locally or from the '
                            'network'
                        )
                    self.data_secret.from_string(await resp.text())

                if self.data_secret.cert:
                    try:
                        await self.data_secret.save()
                    except PermissionError:
                        pass

    async def add_service(self, service_id: int,
                          registration_status: RegistrationStatus = None
                          ) -> Service:
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
            service.registration_status = registration_status
        else:
            service.registration_status = \
                await service.get_registration_status()

        return service
