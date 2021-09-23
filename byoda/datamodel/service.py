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

from byoda.datatypes import CsrSource

from byoda.datamodel.schema import Schema

from byoda.util import SignatureType

from byoda.util.secrets import Secret
from byoda.util.secrets import NetworkServicesCaSecret
from byoda.util.secrets import ServiceCaSecret
from byoda.util.secrets import MembersCaSecret
from byoda.util.secrets import AppsCaSecret
from byoda.util.secrets import ServiceSecret
from byoda.util.secrets import ServiceDataSecret

_LOGGER = logging.getLogger(__name__)

Account = TypeVar('Account', bound='Account')
Network = TypeVar('Network', bound='Network')


class Service:
    '''
    Models a service on a BYODA network.
    This class is used both by the SDK for hosting a service
    and by pods
    '''

    def __init__(self, network: Network = None, filepath: str = None):
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
        self.service_id: int = None

        # The data contract for the service. TODO: versioned schemas
        self.schema: Schema = None

        # Was the schema for the service signed
        self.signed: bool = None

        self.private_key_password: str = network.private_key_password

        # The CA signed by the Services CA of the network
        self.service_ca = None

        # CA signs secrets of new members of the service
        self.members_ca = None

        # CA signs secrets of apps that run with a delegation of
        # the data contract of the service
        self.apps_ca = None

        # The secret used as server cert for incoming TLS connections
        # and as client cert in outbound TLS connections
        self.tls_secret = None

        # The secret used to sign documents, ie. the data contract for
        # the service
        self.data_secret = None

        # The network that the service is a part of. As storage is already
        # set up for the Network object, we can copy it here for the Service
        self.network = network
        self.paths = copy(network.paths)

        self.storage_driver = self.paths.storage_driver

        if filepath:
            self.load_schema(filepath, verify_contract_signatures=False)

        self.storage_driver = network.paths.storage_driver

    @classmethod
    def get_service(cls, network: Network, filepath: str = None,
                    with_private_key: bool = False, password: str = None,
                    ) -> Service:
        '''
        Factory for Service class, loads the service metadata from a local
        file.

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

        self.schema = Schema(
            filepath, self.storage_driver,
        )

        self.service_id = self.schema.service_id

        self.name = self.schema.name

        self.paths.service_id = self.service_id

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

        if not self.schema.signatures[SignatureType.SERVICE]:
            raise ValueError('Schema does not contain a service signature')
        if not self.schema.signatures[SignatureType.NETWORK]:
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

    def create_secrets(self, network_services_ca: NetworkServicesCaSecret,
                       password: str = None) -> None:
        '''
        Creates all the secrets of a service

        :raises PermissionError
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
                          ) -> None:
        '''
        Create the service CA

        :raises: ValueError if the service ca already exists
        '''

        self.service_ca = self._create_secret(
            ServiceCaSecret, network_services_ca
        )

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

        if not issuing_ca:
            # TODO
            if type(secret_cls) != ServiceCaSecret:
                raise ValueError(
                    f'No issuing_ca was provided for creating a '
                    f'{type(secret_cls)}'
                )
            else:
                raise NotImplementedError(
                    'Getting a signed certificate from a network directory'
                    'server is not yet implemented'
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
        issuing_ca.review_csr(csr, source=CsrSource.LOCAL)
        certchain = issuing_ca.sign_csr(csr)
        secret.add_signed_cert(certchain)
        secret.save(password=self.private_key_password)

        return secret

    def load_secrets(self, with_private_key: bool = True, password: str = None
                     ) -> None:
        '''
        Loads all the secrets of a service
        '''
        if self.service_ca:
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

    def validate(self, data: Dict):
        '''
        Validates the data against the json schema for the service
        '''

        self.schema.validate(data)
