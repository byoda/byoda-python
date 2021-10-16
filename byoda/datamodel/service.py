'''
Class for modeling a service on a social network

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

from __future__ import annotations

import logging
from typing import TypeVar, Callable, Dict
from copy import copy

from cryptography.hazmat.primitives import serialization

from byoda.datatypes import CsrSource

from byoda.datamodel.schema import Schema

from byoda.util import SignatureType
from byoda.util import Paths

from byoda.util.secrets import Secret, CSR
from byoda.util.secrets import NetworkServicesCaSecret
from byoda.util.secrets import ServiceCaSecret
from byoda.util.secrets import MembersCaSecret
from byoda.util.secrets import AppsCaSecret
from byoda.util.secrets import ServiceSecret
from byoda.util.secrets import ServiceDataSecret

from byoda import config
from byoda.util.secrets.certchain import CertChain
from byoda.util.secrets.secret import CaSecret

_LOGGER = logging.getLogger(__name__)

Network = TypeVar('Network', bound='Network')

NETWORK_SERVICE_API = 'https://dir.{network}/api/v1/network/service'


class Service:
    '''
    Models a service on a BYODA network.
    This class is used both by the SDK for hosting a service
    and by pods
    '''

    def __init__(self, network: Network = None, filepath: str = None,
                 service_id: int = None):
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
        '''

        self.name: str = None
        self.service_id: int = service_id

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

        self.storage_driver = self.paths.storage_driver

        # If we have enough info, let's make sure the directory exists
        if self.network and self.service_id:
            self.storage_driver.create_directory(
                self.paths.get(Paths.SERVICE_DIR)
            )

        if filepath:
            _LOGGER.info(f'Loading service from file {filepath}')
            self.load_schema(filepath, verify_contract_signatures=False)

    @classmethod
    def get_service(cls, network: Network, filepath: str = None,
                    with_private_key: bool = False, password: str = None,
                    ) -> Service:
        '''
        Factory for Service class, loads the service metadata from a local
        file and verifies its signatures

        :param network: the network to which service belongs
        :param filepath: path to the file containing the data contract

        TODO: load the service metadata from the network directory server
        '''

        service = Service(network=network, filepath=filepath)

        service.load_data_secret(with_private_key, password)
        service.verify_schema_signatures()
        service.schema.generate_graphql_schema()

        _LOGGER.debug(f'Read service from {filepath}')

        return service

    def load_schema(self, filepath: str = None,
                    verify_contract_signatures: bool = True) -> bool:
        '''
        Loads the schema for a service

        :returns: whether schema was signed
        '''

        # TODO: implement validation of the service definition using
        # JSON-Schema

        if filepath is None:
            raise NotImplementedError(
                'Downloading service definitions from the directory server '
                'of a network is not yet implemented'
            )

        self.schema = Schema.get_schema(
            filepath, self.storage_driver,
        )

        self.name = self.schema.name
        self.service_id = self.schema.service_id
        self.paths.service_id = self.service_id

        # We make sure that the directory exists
        self.paths.storage_driver.create_directory(
            self.paths.get(Paths.SERVICE_DIR)
        )

        _LOGGER.debug(
            f'Read service {self.name} wih service_id {self.service_id}'
        )

        if verify_contract_signatures:
            self.verify_schema_signatures()

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
            raise ValueError(
                'Data secret not available to verify service signature'
            )
        if not self.network.data_secret or not self.network.data_secret.cert:
            raise ValueError(
                'Network data secret not available to verify network signature'
            )

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

    def create_secrets(self, network_services_ca: NetworkServicesCaSecret,
                       local: False, password: str = None) -> None:
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

        self.create_service_ca(network_services_ca)

        self.create_apps_ca()
        self.create_members_ca()
        self.create_service_secret()
        self.create_data_secret()

    def create_service_ca(self,
                          network_services_ca: NetworkServicesCaSecret = None,
                          local: bool = False) -> None:
        '''
        Create the service CA

        :param local: should the CSR be signed by a local key or using a
        request to the directory server of the network
        :raises: ValueError if the service ca already exists
        '''

        if local:
            self.service_ca = self._create_secret(
                ServiceCaSecret, network_services_ca
            )
        else:
            self.service_ca = self._create_secret(ServiceCaSecret, None)

    def create_members_ca(self) -> None:
        '''
        Creates the member CA, signed by the Service CA

        :raises: ValueError if no Service CA is available to sign
        the CSR of the member CA
        '''

        self.members_ca = self._create_secret(
            MembersCaSecret, self.service_ca
        )

    def create_apps_ca(self) -> None:
        '''
        Create the CA that signs application secrets
        '''

        self.apps_ca = self._create_secret(AppsCaSecret, self.service_ca)

    def create_service_secret(self) -> None:
        '''
        Creates the service TLS secret, signed by the Service CA

        :raises: ValueError if no Service CA is available to sign
        the CSR of the service secret
        '''

        self.service_secret = self._create_secret(
            ServiceSecret, self.service_ca
        )

    def create_data_secret(self) -> None:
        '''
        Creates the service data secret, signed by the Service CA

        :raises: ValueError if no Service CA is available to sign
        the CSR of the service secret
        '''

        self.data_secret = self._create_secret(
            ServiceDataSecret, self.service_ca
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

        csr = secret.create_csr()
        certchain = self.get_csr_signature(secret_cls, csr, issuing_ca)

        secret.from_signed_cert(certchain)
        secret.save(password=self.private_key_password)

        return secret

    def get_csr_signature(self, secret_cls: Callable, csr: CSR,
                          issuing_ca: CaSecret) -> CertChain:
        '''
        Gets the signed cert(chain) for the CSR. If issuing_ca parameter is
        specified then the CSR will be signed directly by the private key
        of the issuing_ca, otherwise the CSR will be send in a
        POST /api/v1/network/service API call to the directory server of the
        network
        '''
        if issuing_ca:
            issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
            certchain = issuing_ca.sign_csr(csr)
        else:
            if isinstance(secret_cls, ServiceCaSecret):
                raise ValueError(
                    f'No issuing_ca was provided for creating a '
                    f'{type(secret_cls)}'
                )

            # Let's get the ServiceCA cert signed by the NetworkServicesCA
            url = NETWORK_SERVICE_API.format(network=self.network.name)
            csr_pem = csr.public_bytes(serialization.Encoding.PEM)

            response = config.requests.post(
                url, json={'csr': str(csr_pem, 'utf-8')}
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            certchain = CertChain.from_string(
                data['signed_cert'], data['cert_chain']
            )
            # Every time we receive the network data cert, we
            # save it as it could have changed since the last time we
            # got it
            network = config.server.network
            network.data_secret.from_string(
                data['network_data_cert']
            )
            network.data_secret.save(
                password=network.private_key_password, overwrite=True
            )
        return certchain

    def load_secrets(self, with_private_key: bool = True, password: str = None
                     ) -> None:
        '''
        Loads all the secrets of a service
        '''
        if not self.service_ca:
            self.service_ca = ServiceCaSecret(
                self.name, self.service_id, self.network
            )
            self.service_ca.load(
                with_private_key=with_private_key, password=password
            )

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

    def load_data_secret(self, with_private_key: bool, password: str):
        '''
        Loads the certificate of the data secret of the service
        '''

        if not self.data_secret:
            self.data_secret = ServiceDataSecret(
                self.name, self.service_id, self.network
            )
            self.data_secret.load(
                with_private_key=with_private_key, password=password
            )
