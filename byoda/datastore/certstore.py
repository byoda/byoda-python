'''
Class for certificate request processing

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from uuid import UUID
from ipaddress import ip_address

from cryptography import x509

from byoda.datatypes import IdType

from byoda.util.secrets import Secret, CertChain

_LOGGER = logging.getLogger(__name__)


class CertStore:
    '''
    Processing of CSRs and storing signed certs
    '''

    def __init__(self, ca_secret: Secret, connectionstring: str = None):
        '''
        Constructor

        :param ca_secret: the CA cert to sign CSRs with
        :param connectionstring: the location to store processed CSRs
        :returns: (none)
        :raises: NotImplementedError if connectionstring has a value other
        than None

        '''

        if connectionstring:
            raise NotImplementedError('Storing of CSRs not supported yet')

        self.connectionstring = connectionstring
        self.ca_secret = ca_secret

    def sign(self, csr: str, client_ip: ip_address, id_type: IdType
             ) -> CertChain:
        '''
        Evaluate a CSR and sign it

        :param csr: the Certificate Signing Request
        :param client_ip: the originating IP address for the CSR
        :param id_type: what entity is the CSR for, client, service or member
        :returns: the signed certificate
        :raises: KeyError if the Certificate Name is not acceptable,
                 ValueError if there is something else unacceptable in the CSR
        '''

        if isinstance(csr, str):
            csr = str.encode(csr)
        elif isinstance(csr, bytes):
            pass
        else:
            raise ValueError('CSR must be a string or a byte array')

        x509_csr = Secret()
        x509_csr.from_string(csr)

        extension = x509_csr.extensions.get_extension_for_class(
            x509.BasicConstraints
        )
        if extension.value.ca:
            raise ValueError('Certificates with CA bits set are not permitted')

        common_name = x509_csr.review_csr()

        identifier, subdomain = common_name.split('.')

        if subdomain != id_type.value:
            raise ValueError(
                f'Subdomain {subdomain} in common-name does no match the '
                f'identifier type {id_type.value}'
            )

        if id_type == IdType.SERVICE:
            raise NotImplementedError('Service certs are not yet supported')
        elif id_type == IdType.MEMBER:
            raise NotImplementedError('Member certs are not yet supported')

        try:
            uuid = UUID(identifier)
        except ValueError:
            raise ValueError(f'Identifier {identifier} is not a UUID')

        # TODO: add check on whether the UUID is already in use

        certchain = self.ca_secret.sign_csr()

        _LOGGER.info(
            f'Signed CSR for {uuid} for {id_type.value} received from IP '
            f'{str(client_ip)}'
        )
        return certchain.as_byteS()
