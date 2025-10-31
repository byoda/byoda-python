'''
Class for certificate request processing

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from logging import Logger
from logging import getLogger


from ipaddress import ip_address as IpAddress

from cryptography import x509

from byoda.datatypes import IdType

from byoda.secrets.secret import Secret
from byoda.secrets.secret import CertChain
from byoda.secrets.ca_secret import CaSecret

_LOGGER: Logger = getLogger(__name__)


class CertStore:
    '''
    Processing of CSRs and storing signed certs
    '''

    def __init__(self, ca_secret: CaSecret, connectionstring: str = None):
        '''
        Constructor

        :param ca_secret: the CA cert/key to sign CSRs with
        :param connectionstring: the location to store-processed CSRs
        :returns: (none)
        :raises: NotImplementedError if connectionstring has a value other
        than None

        '''

        if connectionstring:
            raise NotImplementedError('Storing of CSRs not supported yet')

        self.connectionstring: str = connectionstring
        self.ca_secret: CaSecret = ca_secret

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

        if type(csr) not in (str, bytes):
            raise ValueError('CSR must be a string or a byte array')

        cert_auth: Secret = self.ca_secret

        csr = Secret.csr_from_string(csr)

        is_ca: bool = False
        try:
            ca_extension: x509.Extension[x509.BasicConstraints] = \
                csr.extensions.get_extension_for_class(x509.BasicConstraints)
            is_ca = ca_extension.value.ca
        except x509.ExtensionNotFound:
            pass

        if cert_auth.max_path_length is None and is_ca:
            raise ValueError('Certificates with CA bits set are not permitted')

        entity_id: str = cert_auth.review_csr(csr)

        if entity_id.id_type == IdType.SERVICE:
            raise NotImplementedError(
                'Service certs are not supported for this API, '
                'only ServiceCA certs'
            )

        # TODO: add check on whether the UUID is already in use
        certchain: CertChain = cert_auth.sign_csr(csr, 365*3)

        new_id_type: str = entity_id.id_type.value.strip('-')
        _LOGGER.info(
            f'Signed the CSR for {entity_id.id} for IdType {new_id_type} '
            f'received from IP {str(remote_addr)}'
        )
        return certchain
