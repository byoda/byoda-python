'''
Cert manipulation

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import datetime
import logging

from copy import copy
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from byoda.datatypes import CsrSource, EntityId

from byoda.storage.filestorage import FileStorage

from .secret import Secret, CertChain

_LOGGER = logging.getLogger(__name__)

_RSA_KEYSIZE = 3072

_BYODA_DIR = '/.byoda/'
_ROOT_DIR = os.environ['HOME'] + _BYODA_DIR

VALID_SIGNATURE_ALGORITHMS = set(
    [
        'sha256WithRSAEncryption'
    ]
)
VALID_SIGNATURE_HASHES = set(
    [
        'sha256'
    ]
)
IGNORED_X509_NAMES = set(['C', 'ST', 'L', 'O'])

CSR = x509.CertificateSigningRequest


class CaSecret(Secret):
    '''
    Interface class for the various types of secrets BYODA uses

    Properties:
    - cert                 : instance of cryptography.x509
    - key                  : instance of
                             cryptography.hazmat.primitives.asymmetric.rsa
    - password             : string protecting the private key
    - shared_key           : unprotected shared secret used by Fernet
    - protected_shared_key : protected shared secret used by Fernet
    - fernet               : instance of cryptography.fernet.Fernet
    '''

    def __init__(self, cert_file: str = None, key_file: str = None,
                 storage_driver: FileStorage = None):
        '''
        Constructor

        :param cert_file: string with the path to the certificate file
        :param key_file: string with the path to the key file. If supplied
        :returns: (none)
        :raises: (none)
        '''

        super().__init__(cert_file, key_file, storage_driver)

        self.is_root_cert = False

        self.ca = True

        # These are the different identity types of the
        # certificates for which this secret will sign
        # CSRs
        self.accepted_csrs = []

    def review_csr(self, csr: CSR, source: CsrSource = None) -> str:
        '''
        Check whether the CSR meets our requirements

        :param csr: the certificate signing request to be reviewed
        :returns: commonname of the certificate
        :raises: ValueError, NotImplementedError, PermissionError
        '''

        if not self.ca:
            raise NotImplementedError('Only CAs need to review CNs')

        if not self.private_key_file:
            raise ValueError('CSR received while we do not have a private key')

        _LOGGER.debug('Reviewing cert sign request')

        if not self.ca:
            raise ValueError('Only CAs review CSRs')

        if not csr.is_signature_valid:
            raise ValueError('CSR with invalid signature')

        sign_algo = csr.signature_algorithm_oid._name
        if sign_algo not in VALID_SIGNATURE_ALGORITHMS:
            raise ValueError(f'Invalid algorithm: {sign_algo}')

        hash_algo = csr.signature_hash_algorithm.name
        if hash_algo not in VALID_SIGNATURE_HASHES:
            raise ValueError(f'Invalid algorithm: {hash_algo}')

        # We start parsing the Subject of the CSR, which
        # consists of a list of 'Relative' Distinguished Names
        distinguished_name = ','.join(
            [rdns.rfc4514_string() for rdns in csr.subject.rdns]
        )

        common_name = self.review_distinguishedname(distinguished_name)

        return common_name

    def review_distinguishedname(self, name: str) -> str:
        '''
        Reviews the DN of a certificate, extracts the commonname (CN),
        which is the only field we are interrested in

        :param distinguishedname: the DN from the cert
        :returns: commonname
        :raises: ValueError if the commonname can not be found in the
        dstinguishedname
        '''

        commonname = None
        bits = name.split(',')
        for dn in bits:
            key, value = dn.split('=')
            if not key or not value:
                raise ValueError(f'Invalid commonname: {name}')
            if key in IGNORED_X509_NAMES:
                continue
            if key == 'CN':
                commonname = value
                return commonname
            else:
                raise ValueError(f'Unknown distinguished name: {key}')

        raise ValueError(f'commonname not found in {name}')

    def review_commonname(self, commonname: str, uuid_identifier=True,
                          check_service_id=True) -> str:
        '''
        Checks if the structure of common name matches of a byoda secret.
        Parses the entity type, the identifier and optionally the service_id
        from the common name

        :param commonname: the commonname to check
        :param uuid_identifier: whether to check if the identifier is a UUID
        :param check_service_id: should any service_id in the common name
        match the service_id attribute of the secret?
        :returns: commonname with the network domain stripped off, ie. for
        'uuid.accounts.byoda.net' it will return 'uuid.accounts'.
        :raises: ValueError if the commonname is not a string
        '''

        if not self.ca:
            raise NotImplementedError('Only CAs need to review CNs')

        if not isinstance(commonname, str):
            raise ValueError(
                f'Common name must be of type str, not {type(commonname)}'
            )

        postfix = '.' + self.network
        if not commonname.endswith(postfix):
            raise PermissionError(
                f'Commonname {commonname} is not for network {self.network}'
            )

        commonname_prefix = commonname[:-1 * len(postfix)]

        bits = commonname_prefix.split('.')
        if len(bits) != 2:
            raise ValueError(f'Invalid number of domain levels: {commonname}')

        identifier, subdomain = bits

        id_type = None
        longest_match = 0
        for id_type_iter in self.accepted_csrs:
            length = len(id_type_iter.value)
            if (subdomain.startswith(id_type_iter.value)
                    and length > longest_match):
                id_type = id_type_iter
                longest_match = length

        if not id_type:
            raise PermissionError(
                f'Service CA does not sign CSR for subdomain {subdomain}'
            )

        if uuid_identifier:
            try:
                identifier = UUID(identifier)
            except ValueError:
                raise ValueError(
                    f'Common name {commonname} does not have a valid UUID '
                    'identifier'
                )

        service_id = subdomain[len(id_type.value):]

        if service_id == '':
            service_id = None
        elif service_id:
            service_id = int(service_id)

        if check_service_id:
            if self.service_id != service_id:
                raise PermissionError(
                    f'Request for incorrect service {service_id} in common '
                    f'name {commonname}'
                )

        return EntityId(id_type, identifier, service_id)

    def sign_csr(self, csr: CSR, expire: int = 365) -> CertChain:
        '''
        Sign a csr with our private key

        :param - csr: X509.CertificateSigningRequest
        :param int expire: after how many days the cert should
        :returns: the signed cert and the certchain excluding the root CA
        :raises: ValueError, KeyError
        '''

        if not self.ca:
            raise ValueError('Only CAs sign CSRs')

        if not self.private_key:
            raise KeyError('Private key not loaded')

        try:
            extension = csr.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
            is_ca = extension.value.ca
        except x509.ExtensionNotFound:
            is_ca = False

        _LOGGER.debug('Signing cert with cert %s', self.common_name)
        cert = x509.CertificateBuilder().subject_name(
            csr.subject
        ).issuer_name(
            self.cert.subject
        ).public_key(
            csr.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=expire)
        ).add_extension(
            x509.BasicConstraints(
                ca=is_ca, path_length=None
            ), critical=True,
        ).sign(self.private_key, hashes.SHA256())

        cert_chain = copy(self.cert_chain)
        if not self.is_root_cert:
            cert_chain.append(self.cert)

        return CertChain(cert, cert_chain)

    def create_selfsigned_cert(self, expire=365, ca=False):
        '''
        Create a self_signed certificate

        :param expire: days after which the cert should expire
        :param bool: is the cert for a CA
        :returns: (none)
        :raises: (none)
        '''

        subject = issuer = self.get_cert_name()

        self.is_root_cert = True
        self.cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            self.private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(expire)
        ).add_extension(
            x509.BasicConstraints(
                ca=ca, path_length=None
            ), critical=True,
        ).sign(self.private_key, hashes.SHA256())
