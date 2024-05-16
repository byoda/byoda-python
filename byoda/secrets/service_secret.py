'''
Cert manipulation for service secrets: Service CA, Service Members CA and
Service secret

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from copy import copy
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger

from cryptography.x509 import CertificateSigningRequest

from byoda.util.paths import Paths

from byoda.datatypes import IdType, EntityId

from .secret import Secret


_LOGGER: Logger = getLogger(__name__)

Network = TypeVar('Network', bound='Network')


class ServiceSecret(Secret):
    __slots__: list[str] = ['network', 'service_id']

    def __init__(self, service_id: int, network: Network):
        '''
        Class for the service secret

        :param Paths paths: instance of Paths class defining the directory,
        structure and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        self.paths: Paths = copy(network.paths)
        self.network: str = network.name

        super().__init__(
            cert_file=self.paths.get(
                Paths.SERVICE_CERT_FILE, service_id=service_id
            ),
            key_file=self.paths.get(
                Paths.SERVICE_KEY_FILE, service_id=service_id
            ),
            storage_driver=self.paths.storage_driver
        )
        self.service_id: int = int(service_id)
        self.id_type: IdType = IdType.SERVICE

    async def create_csr(self, renew: bool = False
                         ) -> CertificateSigningRequest:
        '''
        Creates an RSA private key and X.509 CSR

        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: csr
        :raises: ValueError if the Secret instance already has a private key
        or cert
        '''

        # TODO: SECURITY: add constraints
        common_name = ServiceSecret.create_commonname(
            self.service_id, self.network
        )

        return await super().create_csr(common_name, ca=self.ca, renew=renew)

    def review_commonname(self, commonname: str) -> EntityId:
        '''
        Checks if the structure of common name matches with a common name of
        an ServiceSecret and returns the entity identifier parsed from
        the commonname

        :param commonname: the commonname to check
        :returns: service entity
        :raises: ValueError if the commonname is not valid for this class
        '''

        # Checks on commonname type and the network postfix
        entity_id = super().review_commonname(commonname)

        return entity_id

    @staticmethod
    def create_commonname(service_id: int, network: str) -> str:
        '''
        Returns FQDN to use in the common name of a secret
        '''

        service_id = int(service_id)
        if not isinstance(network, str):
            raise TypeError(
                f'Network parameter must be a string, not a {type(network)}'
            )

        common_name = f'service.{IdType.SERVICE.value}{service_id}.{network}'

        return common_name

    @staticmethod
    def parse_commonname(commonname: str, network: Network) -> EntityId:
        '''
        Validate the common name of a Service secret
        :returns: service_id
        Extracts the service_id from the common name of a Service secret
        '''

        entity_id = Secret.review_commonname_by_parameters(
            commonname, network.name, check_service_id=False,
            uuid_identifier=False
        )

        if entity_id.id_type != IdType.SERVICE:
            raise ValueError(f'Invalid {commonname} for a Service secret')

        if entity_id.service_id is None:
            raise ValueError(f'No service ID in commonname {commonname}')

        return entity_id

    def save_tmp_private_key(self):
        '''
        Save the private key for the ServiceSecret so angie and the python
        requests module can use it.
        '''
        return super().save_tmp_private_key(
            filepath=self.get_tmp_private_key_filepath()
        )

    def get_tmp_private_key_filepath(self) -> str:
        '''
        Gets the location where on local storage the unprotected private
        key is stored
        '''

        return f'/var/tmp/service-{self.service_id}.key'
