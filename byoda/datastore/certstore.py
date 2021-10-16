'''
Class for certificate request processing

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from ipaddress import ip_address as IpAddress

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

    def sign(self, csr: str, id_type: IdType, remote_addr: IpAddress
             ) -> CertChain:
        '''
        Evaluate a CSR and sign it

        :param csr: the Certificate Signing Request
        :param id_type: what entity is the CSR for, client, service or member
        :param remote_addr: the originating IP address for the CSR
        :returns: the signed certificate and its certchain
        :raises: KeyError if the Certificate Name is not acceptable,
                 ValueError if there is something else unacceptable in the CSR
        '''

        if type(csr) in (str, bytes):
            pass
        else:
            raise ValueError('CSR must be a string or a byte array')

        cert_auth = self.ca_secret

        x509_csr = Secret()
        csr = x509_csr.csr_from_string(csr)

        extension = csr.extensions.get_extension_for_class(
            x509.BasicConstraints
        )
        if not cert_auth.signs_ca_certs and extension.value.ca:
            raise ValueError('Certificates with CA bits set are not permitted')

        entity_id = cert_auth.review_csr(csr)

        if entity_id.id_type == IdType.SERVICE:
            raise NotImplementedError('Service certs are not yet supported')
        elif entity_id.id_type == IdType.MEMBER:
            raise NotImplementedError('Member certs are not yet supported')

        # TODO: add check on whether the UUID is already in use

        certchain = cert_auth.sign_csr(csr, 365*3)

        id_type = entity_id.id_type.value.strip('-')
        _LOGGER.info(
            f'Signed the CSR for {entity_id.id} for {id_type} '
            f'received from IP {str(remote_addr)}'
        )
        return certchain
