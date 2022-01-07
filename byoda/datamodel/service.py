'''
Class for modeling a service on a social network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''


import os
import logging
import socket
import json
from typing import TypeVar, Callable, Dict
from copy import copy
from enum import Enum

import passgen

from cryptography.hazmat.primitives import serialization

from byoda.datastore.dnsdb import DnsRecordType

from byoda.storage import FileStorage

from byoda.datatypes import CsrSource
from byoda.datatypes import ServerType

from byoda.datamodel.schema import Schema

from byoda.util.api_client import ApiClient

from byoda.util import SignatureType
from byoda.util import Paths

from byoda.datatypes import IdType
from byoda.util.api_client.restapi_client import HttpMethod, RestApiClient

from byoda.secrets import Secret, CSR
from byoda.secrets import CaSecret
from byoda.secrets import NetworkServicesCaSecret
from byoda.secrets import NetworkDataSecret
from byoda.secrets import ServiceCaSecret
from byoda.secrets import MembersCaSecret
from byoda.secrets import AppsCaSecret
from byoda.secrets import ServiceSecret
from byoda.secrets import ServiceDataSecret

from byoda import config

_LOGGER = logging.getLogger(__name__)

# The well-known service IDs
BYODA_PRIVATE_SERVICE = 0
BYODA_ADDRESSBOOK_SERVICE = 1

Network = TypeVar('Network', bound='Network')


class RegistrationStatus(Enum):
    # flake8: noqa=E221
    Unknown         = 0
    CsrSigned       = 1
    Registered      = 2
    SchemaSigned    = 3


class Service:
    '''
    Models a service on a BYODA network.
    This class is used both by the SDK for hosting a service
    and by pods
    '''

    def __init__(self, network: Network = None, filepath: str = None,
                 service_id: int = None, storage_driver: FileStorage = None):
        '''
        Constructor, can be used by the service but also by the
        network, an app or an account or member to model the service.
        Because of this, only minimal initiation of the instance is
        done and depending on the user case, additional methods must
        be called to load all the needed info for the service.

        :param network: Network the service is part of
        :param filepath: the file with the service schema/contract. If this
        optional parameter is specified, the signatures of the schema/contract
        will not be verified.
        :param service_id: the service_id for the service
        '''

        self.name: str = None
        self.service_id: int = service_id

        self.registration_status: RegistrationStatus = \
            RegistrationStatus.Unknown

        # The data contract for the service. TODO: versioned schemas
        self.schema: Schema = None

        # Was the schema for the service signed
        self.signed: bool = None

        self.private_key_password: str = network.private_key_password

        # The CA signed by the Services CA of the network
        self.service_ca: ServiceCaSecret = None

        # CA signs secrets of new members of the service
        self.members_ca: MembersCaSecret = None

        # CA signs secrets of apps that run with a delegation of
        # the data contract of the service
        self.apps_ca: AppsCaSecret = None

        # The secret used as server cert for incoming TLS connections
        # and as client cert in outbound TLS connections
        self.tls_secret: ServiceSecret = None

        # The secret used to sign documents, ie. the data contract for
        # the service
        self.data_secret: ServiceDataSecret = None

        # The network that the service is a part of. As storage is already
        # set up for the Network object, we can copy it here for the Service
        self.network: Network = network
        self.paths: Paths = copy(network.paths)
        self.paths.service_id = service_id

        if storage_driver:
            self.storage_driver = storage_driver
        else:
            self.storage_driver = self.paths.storage_driver

        if filepath:
            raw_data = self.storage_driver.read(filepath)
            data = json.loads(raw_data)
            self.service_id = data['service_id']
            self.name = data['name']

    @classmethod
    def get_service(cls, network: Network, filepath: str = None,
                    with_private_key: bool = False, password: str = None):
        '''
        Factory for Service class, loads the service metadata from a local
        file and verifies its signatures

        :param network: the network to which service belongs
        :param filepath: path to the file containing the data contract

        '''

        service = Service(network=network, filepath=filepath)

        service.load_data_secret(with_private_key, password)

        service.load_schema(filepath)
        service.schema.generate_graphql_schema()

        _LOGGER.debug(f'Read service from {filepath}')

        return service

    @property
    def fqdn(self):
        return self.tls_secret.common_name

    def load_schema(self, filepath: str = None,
                    verify_contract_signatures: bool = True) -> bool:
        '''
        Loads the schema for a service

        :returns: whether schema was signed
        '''

        # TODO: implement validation of the service definition using
        # JSON-Schema meta schema

        if filepath is None:
            if not verify_contract_signatures:
                raise ValueError(
                    'The signatures for Schemas downloaded from the network '
                    'must always be validated'
                )
            raise NotImplementedError(
                'Downloading service definitions from the directory server '
                'of a network is not yet implemented'
            )

        self.schema = Schema.get_schema(
            filepath, self.storage_driver,
            service_data_secret=self.data_secret,
            network_data_secret=self.network.data_secret,
            verify_contract_signatures=verify_contract_signatures
        )

        self.name = self.schema.name
        self.service_id = self.schema.service_id
        self.paths.service_id = self.service_id

        _LOGGER.debug(
            f'Read service {self.name} wih service_id {self.service_id}'
        )

        if verify_contract_signatures:
            self.verify_schema_signatures()
            self.registration_status = RegistrationStatus.SchemaSigned

    def save_schema(self, data: str, filepath: str = None):
        '''
        Saves the raw data of the service contract to the Service directory
        '''

        if not filepath:
            filepath = self.paths.get(Paths.SERVICE_FILE, service_id=self.service_id)

        self.storage_driver.write(filepath, data)

    def verify_schema_signatures(self):
        '''
        Verify the signatures for the schema, a.k.a. data contract

        :raises: ValueError
        '''

        if not self.schema.signatures[SignatureType.SERVICE.value]:
            raise ValueError('Schema does not contain a service signature')
        if not self.schema.signatures[SignatureType.NETWORK.value]:
            raise ValueError('Schema does not contain a network signature')
        if not self.data_secret or not self.data_secret.cert:
            # Let's see if we can read the data secret ourselves
            self.data_secret = ServiceDataSecret(None, self.service_id, self.network)
            self.data_secret.load(with_private_key=False)
        if not self.network.data_secret or not self.network.data_secret.cert:
            self.network.data_secret = NetworkDataSecret(self.network.paths)
            self.network.data_secret.load(with_private_key=False)

        self.schema.verify_signature(self.data_secret, SignatureType.SERVICE)

        _LOGGER.debug(
            'Verified service signature for service %s', self.service_id
        )

        self.schema.verify_signature(
            self.network.data_secret, SignatureType.NETWORK
        )

        _LOGGER.debug(
            'Verified network signature for service %s', self.service_id
        )

    def validate(self, data: Dict):
        '''
        Validates the data against the json schema for the service
        '''

        self.schema.validate(data)

    def schema_file_exists(self) -> bool:
        '''
        Check if the file with the schema exists on the local file system
        '''

        server = config.server

        if server.server_type not in (ServerType.Service, ServerType.Directory):
            raise ValueError(
                'This function should only be called from Directory- and '
                f'Service-servers, not from a {type(server)}'
            )

        filepath = self.paths.get(Paths.SERVICE_FILE, service_id=self.service_id)
        return os.path.exists(filepath)

    def create_secrets(self, network_services_ca: NetworkServicesCaSecret,
                       local: bool = False, password: str = None) -> None:
        '''
        Creates all the secrets of a service

        :raises RuntimeError, PermissionError
        '''

        if (self.service_ca or self.members_ca or self.apps_ca or
                self.tls_secret or self.data_secret):
            raise RuntimeError('One or more service secrets already exist')

        if password:
            self.private_key_password = password

        if not self.paths.service_directory_exists(self.service_id):
            self.paths.create_service_directory(self.service_id)

        if not self.paths.secrets_directory_exists():
            self.paths.create_secrets_directory()

        self.create_service_ca(network_services_ca, local=True)

        self.create_apps_ca()
        self.create_members_ca()
        self.create_tls_secret()
        self.create_data_secret()

    def create_service_ca(self,
                          network_services_ca: NetworkServicesCaSecret = None,
                          local: bool = False) -> None:
        '''
        Create the service CA using a generated password for the private key. This
        password is different then the passwords for the other secrets as the
        Service CA should have additional security implemented and should be stored
        off-line

        :param local: should the CSR be signed by a local key or using a
        request to the directory server of the network
        :raises: ValueError if the service ca already exists
        '''

        private_key_password = passgen.passgen(length=48)

        if local:
            self.service_ca = self._create_secret(
                ServiceCaSecret, network_services_ca,
                private_key_password=private_key_password
            )
        else:
            self.service_ca = self._create_secret(
                ServiceCaSecret, None, private_key_password=private_key_password
            )
        _LOGGER.info(
            '!!! Private key password for the off-line Service CA: '
            f'{private_key_password}'
        )
    def create_members_ca(self) -> None:
        '''
        Creates the member CA, signed by the Service CA

        :raises: ValueError if no Service CA is available to sign
        the CSR of the member CA
        '''

        self.members_ca = self._create_secret(
            MembersCaSecret, self.service_ca,
            private_key_password=self.private_key_password
        )

    def create_apps_ca(self) -> None:
        '''
        Create the CA that signs application secrets
        '''

        self.apps_ca = self._create_secret(
            AppsCaSecret, self.service_ca,
            private_key_password=self.private_key_password
        )

    def create_tls_secret(self) -> None:
        '''
        Creates the service TLS secret, signed by the Service CA

        :raises: ValueError if no Service CA is available to sign
        the CSR of the service secret
        '''

        self.tls_secret = self._create_secret(
            ServiceSecret, self.service_ca,
            private_key_password=self.private_key_password
        )

    def create_data_secret(self) -> None:
        '''
        Creates the service data secret, signed by the Service CA

        :raises: ValueError if no Service CA is available to sign
        the CSR of the service secret
        '''

        self.data_secret = self._create_secret(
            ServiceDataSecret, self.service_ca,
            private_key_password=self.private_key_password
        )

    def _create_secret(self, secret_cls: Callable, issuing_ca: Secret,
                       private_key_password: str = None) -> Secret:
        '''
        Abstraction for creating secrets for the Service class to avoid
        repetition of code for creating the various member secrets of the
        Service class

        :param secret_cls: callable for one of the classes derived from
        byoda.util.secrets.Secret
        :raises: ValueError, NotImplementedError
        '''

        if not self.name or self.service_id is None:
            raise ValueError(
                'Name and service_id of the service have not been defined'
            )

        secret = secret_cls(
            self.name, self.service_id, network=self.network
        )

        if secret.cert_file_exists():
            raise ValueError(
                f'{type(secret)} cert for {self.name} ({self.service_id}) '
                'already exists'
            )

        if secret.private_key_file_exists():
            raise ValueError(
                f'{type(secret)} key for {self.name} ({self.service_id}) '
                'already exists'
            )

        # TODO: SECURITY: add constraints
        csr = secret.create_csr()
        self.get_csr_signature(
            secret, csr, issuing_ca, private_key_password=private_key_password
        )

        return secret

    def get_csr_signature(self, secret: Secret, csr: CSR,
                          issuing_ca: CaSecret,
                          private_key_password: str = None) -> None:
        '''
        Gets the signed cert(chain) for the CSR and saves returned cert and the
        existing private key.
        If the issuing_ca parameter is specified then the CSR will be signed
        directly by the private key of the issuing_ca, otherwise the CSR will be
        send in a POST /api/v1/network/service API call to the directory server
        of the network
        '''

        if (isinstance(secret, ServiceCaSecret) and (
                self.registration_status != RegistrationStatus.Unknown
                or secret.cert_file_exists())):
            # TODO: support renewal of ServiceCA cert
            raise ValueError('ServiceCA cert has already been signed')

        if issuing_ca:
            # We have the private key of the issuing CA so can
            # sign ourselves and be done with it
            issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
            certchain = issuing_ca.sign_csr(csr)
            secret.from_signed_cert(certchain)
            secret.save(password=private_key_password, overwrite=False)
            # We do not set self.registration_status as locally signing
            # does not provide information about the status of service in
            # the network
            return

        if not isinstance(secret, ServiceCaSecret):
            raise ValueError(
                    f'No issuing_ca was provided for creating a '
                    f'{type(secret)}'
                )

        # We have to get our signature from the directory server
        data = {
            'csr': str(
                csr.public_bytes(serialization.Encoding.PEM), 'utf-8'
            )
        }

        url = self.paths.get(Paths.NETWORKSERVICE_API)
        response = RestApiClient.call(
            url, HttpMethod.POST, data=data
        )
        if response.status_code != 201:
            raise ValueError(
                f'Failed to POST to API {Paths.NETWORKSERVICE_API}: '
                f'{response.status_code}'
            )
        data = response.json()
        secret.from_string(data['signed_cert'] + data['cert_chain'])
        self.registration_status = RegistrationStatus.CsrSigned
        secret.save(password=private_key_password, overwrite=False)

        # Every time we receive the network data cert, we
        # save it as it could have changed since the last time we
        # got it
        network = config.server.network
        if not network.data_secret:
            network.data_secret = NetworkDataSecret(network.paths)
        network.data_secret.from_string(data['network_data_cert_chain'])
        network.data_secret.save(overwrite=True)

    @staticmethod
    def is_registered(service_id: int,
                      registration_status: RegistrationStatus = None) -> bool:
        '''
        Checks is the service is registered in the network. When running
        on the directory server, this can check whether a CSR was signed,
        whether an IP address for the service registered and where the
        serice schema/data contract was signed by the network.
        :param registration_status: if not defined, any status except for
        RegistrationStatus.Unknown will result in True being returned.
        It is not allowed to specify RegistrationStatus.Unknown. For other
        values, the value is compared to the registration status of the service
        '''

        server = config.server
        network = config.server.network

        if registration_status == RegistrationStatus.Unknown:
            raise ValueError('Can not check on unknown registration status')

        if server.server_type not in (ServerType.Directory, ServerType.Service):
            if registration_status != RegistrationStatus.SchemaSigned:
                raise ValueError(
                f'Can not check registration status {registration_status.value} '
                f'on servers of type {type(server)}'
            )

        service = Service(network, service_id=service_id)
        status = service.get_registration_status()

        if status == RegistrationStatus.Unknown:
            return False

        if not registration_status:
            return True

        return status == registration_status.value

    def get_registration_status(self) -> RegistrationStatus:
        '''
        Checks what the registration status if of a service in the
        Service server or the Directory server.
        '''
        server = config.server

        if not self.schema:
            if self.schema_file_exists():
                if not self.data_secret or not self.data_secret.cert():
                    self.load_data_secret(with_private_key=False, password=None)

                self.load_schema(self.paths.get(Paths.SERVICE_FILE))

        if self.schema and self.schema.signatures.get('network'):
            return RegistrationStatus.SchemaSigned

        if server.server_type == ServerType.Directory:
            try:
                self.network.dnsdb.lookup(
                    None, IdType.SERVICE, DnsRecordType.A,
                    service_id=self.service_id,
                )
                return RegistrationStatus.Registered
            except KeyError:
                _LOGGER.debug(f'DB lookup of service {self.service_id} failed')
        else:
            fqdn = ServiceSecret.create_commonname(
                self.service_id, self.network.name
            )
            try:
                socket.gethostbyname(fqdn)
                return RegistrationStatus.Registered
            except socket.gaierror:
                _LOGGER.debug(f'DNS lookup of {fqdn} failed')

        if not self.service_ca:
            self.service_ca = ServiceCaSecret(None, self.service_id, server.network)
            if self.service_ca.cert_file_exists():
                if isinstance(server, ServiceServer):
                    self.service_ca.load(
                        with_private_key=True, password=self.private_key_password
                    )
                else:
                    self.service_ca.load(with_private_key=False)

                return RegistrationStatus.CsrSigned
        else:
            if self.service_ca.cert:
                return RegistrationStatus.CsrSigned

        return RegistrationStatus.Unknown

    def register_service(self):
        '''
        Registers the service with the network using the Service TLS secret

        :raises: ValueError if the function is not called by a
        ServerType.Service
        '''

        server = config.server
        if server and not server.server_type == ServerType.Service:
            raise ValueError('Only Service servers can register a service')

        if self.registration_status == RegistrationStatus.Unknown:
            raise ValueError(
                'Can not register a service before its CSR has been signed '
                'by the network'
            )

        key_path = self.tls_secret.save_tmp_private_key()
        data_certchain = {'certchain': self.data_secret.certchain_as_pem()}

        url = self.paths.get(Paths.NETWORKSERVICE_API)
        response = RestApiClient.call(
            url, HttpMethod.PUT, secret=self.tls_secret, data=data_certchain,
            service_id=self.service_id
        )
        return response

    def download_schema(self, save: bool = True, filepath: str = None) -> str:
        '''
        Downloads the latest schema from the webserver of the service

        :param filepath: location where to store the schema. If not specified,
        the default location will be used
        :returns: the schema as string
        '''

        if save:
            # Resolve any variables in the value for the filepath variable
            if not filepath:
                filepath = self.paths.get(Paths.SERVICE_FILE, self.service_id)
            else:
                filepath = self.paths.get(filepath, service_id=self.service_id)

        resp = ApiClient.call(
            Paths.SERVICE_CONTRACT_DOWNLOAD, service_id=self.service_id
        )
        if resp.status_code == 200:
            if save:
                self.save_schema(resp.text, filepath=filepath)

            return resp.text

        raise FileNotFoundError(
            f'Download of service schema failed: {resp.status_code}'
        )

    def load_secrets(self, with_private_key: bool = True, password: str = None,
                     service_ca_password=None) -> None:
        '''
        Loads all the secrets of a service

        :param with_private_key: Load the private keys for all secrets except the
        Service CA key
        :param password: password to use for private keys of all secrets except
        the Service CA
        :param service_ca_password: optional password to use for private key of the
        Service CA. If not specified, only the cert of the Service CA will be loaded.
        '''

        if not self.service_ca:
            self.service_ca = ServiceCaSecret(
                self.name, self.service_id, self.network
            )
            if service_ca_password:
                self.service_ca.load(
                    with_private_key=True, password=service_ca_password
                )
            else:
                self.service_ca.load(with_private_key=False)

        if not self.apps_ca:
            self.apps_ca = AppsCaSecret(
                self.name, self.service_id, self.network
            )
            self.apps_ca.load(
                with_private_key=with_private_key, password=password
            )

        if not self.members_ca:
            self.members_ca = MembersCaSecret(
                None, self.service_id, self.network
            )
            self.members_ca.load(
                with_private_key=with_private_key, password=password
            )

        if not self.tls_secret:
            self.tls_secret = ServiceSecret(
                self.name, self.service_id, self.network
            )
            self.tls_secret.load(
                with_private_key=with_private_key, password=password
            )

        if not self.data_secret:
            self.load_data_secret(with_private_key, password=password)

        # We use the service secret as client TLS cert for outbound
        # requests. We only do this if we read the private key
        # for the TLS/service secret
        if with_private_key:
            filepath = self.tls_secret.save_tmp_private_key()
            config.requests.cert = (self.tls_secret.cert_file, filepath)

    def load_data_secret(self, with_private_key: bool, password: str = None,
                         download: bool = False) -> None:
        '''
        Loads the certificate of the data secret of the service
        '''

        if with_private_key and not password:
            raise ValueError('Can not read data secret private key without password')

        if not self.data_secret:
            self.data_secret = ServiceDataSecret(
                self.name, self.service_id, self.network
            )

            if not self.data_secret.cert_file_exists():
                if download:
                    if with_private_key:
                        raise ValueError(
                            'Can not download private key of the secret from '
                            'the network'
                        )
                    self.download_data_secret()
                else:
                    _LOGGER.exception(
                        'Could not read service data secret for service: '
                        f'{self.service_id}: {self.data_secret.cert_file}'
                    )
                    raise FileNotFoundError(self.data_secret.cert_file)
            else:
                self.data_secret.load(
                    with_private_key=with_private_key, password=password
                )

    def download_data_secret(self, save: bool = True, failhard: bool = False) -> str:
        '''
        Downloads the data secret from the web service for the service

        :returns: the cert in PEM format
        '''

        try:
            resp = ApiClient.call(
                Paths.SERVICE_DATACERT_DOWNLOAD, service_id=self.service_id
            )
        except RuntimeError:
            if failhard:
                raise
            else:
                return None

        if resp.status_code == 200:
            if save:
                self.data_secret = ServiceDataSecret(None, self.service_id, self.network)
                self.data_secret.from_string(resp.text)
                self.data_secret.save(overwrite=(not failhard))

            return resp.text

        raise FileNotFoundError(
            f'Could not download data cert for service {self.service_id}: '
            f'{resp.status_code}'
        )

