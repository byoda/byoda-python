'''
Cert manipulation

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import os

from copy import deepcopy
from typing import override
from logging import Logger
from logging import getLogger
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes

from byoda.datatypes import EntityId
from byoda.datatypes import IdType
from byoda.datatypes import CsrSource

from byoda.storage.filestorage import FileStorage

from .secret import Secret
from .secret import CertChain

_LOGGER: Logger = getLogger(__name__)

_BYODA_DIR: str = '/.byoda/'
_ROOT_DIR: str = os.environ['HOME'] + _BYODA_DIR

CSR = x509.CertificateSigningRequest


class CaSecret(Secret):
    __slots__: list[str] = []

    # When should a CA secret be renewed
    RENEW_WANTED: datetime = datetime.now(tz=UTC) + timedelta(days=180)
    RENEW_NEEDED: datetime = datetime.now(tz=UTC) + timedelta(days=90)

    # CSRs that we are willing to sign and what we set for their expiration
    _ACCEPTED_CSRS: dict[IdType, int] = {}

    # Maximum length of path in CA hierarchy under us.
    _PATHLEN: int | None = 1

    VALID_SIGNATURE_ALGORITHMS: set[str] = {
        'sha256WithRSAEncryption',
        'ed25519',
        'ecdsa-with-SHA256'
    }

    VALID_SIGNATURE_HASHES: set[str] = {'sha256'}

    IGNORED_X509_NAMES: set[str] = {'C', 'ST', 'L', 'O'}

    _KEY_USAGE_CONSTRAINTS: dict[str, bool] = {
                'digital_signature': True,
                'content_commitment': True,
                'key_encipherment': True,
                'data_encipherment': True,
                'key_agreement': True,
                'key_cert_sign': True,
                'crl_sign': True,
                'encipher_only': False,
                'decipher_only': False,
    }

    # Per CABforum Baseline Reqquirements (v1.3.4) 7.2.2g, CAs must include
    # all EKUs that CSRs it would want to sign include.
    # See https://serverfault.com/questions/785108/why-does-openvpn-give-the-error-unsupported-certificate-purpose-for-an-interm        # noqa: E501
    _EXTENDED_KEY_USAGE: list[x509.ObjectIdentifier] = [
        x509.ExtendedKeyUsageOID.OCSP_SIGNING,
        x509.ExtendedKeyUsageOID.CERTIFICATE_TRANSPARENCY,
        x509.ExtendedKeyUsageOID.SERVER_AUTH,
        x509.ExtendedKeyUsageOID.CLIENT_AUTH,
        x509.ExtendedKeyUsageOID.CODE_SIGNING,
        x509.ExtendedKeyUsageOID.EMAIL_PROTECTION,
        x509.ExtendedKeyUsageOID.TIME_STAMPING,
        # x509.ExtendedKeyUsageOID.SMARTCARD_LOGON,
        # x509.ExtendedKeyUsageOID.KERBEROS_PKINIT_KDC,
        # x509.ExtendedKeyUsageOID.IPSEC_IKE,
    ]

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

    @override
    def __init__(self, cert_file: str = None, key_file: str = None,
                 storage_driver: FileStorage = None) -> None:
        '''
        Constructor

        :param cert_file: string with the path to the certificate file
        :param key_file: string with the path to the key file. If supplied
        :returns: (none)
        :raises: (none)
        '''

        super().__init__(cert_file, key_file, storage_driver)

        # X.509 constraints
        self.ca: bool = True
        self.max_path_length: int = self._PATHLEN
        self.key_usage_constraints: dict[str, bool] = \
            CaSecret._KEY_USAGE_CONSTRAINTS
        self.extended_key_usage: dict[str, x509.ObjectIdentifier] = \
            CaSecret._EXTENDED_KEY_USAGE

        # These are the different identity types of the
        # certificates for which this secret will sign
        # CSRs
        self.accepted_csrs: dict[IdType, int] = self._ACCEPTED_CSRS

    @override
    def review_csr(self, csr: CSR, source: CsrSource = None) -> str:
        '''
        Check whether the CSR meets our requirements

        :param csr: the certificate signing request to be reviewed
        :returns: commonname of the certificate
        :raises: ValueError, NotImplementedError, PermissionError
        '''

        if not self.private_key_file:
            raise ValueError('CSR received while we do not have a private key')

        _LOGGER.debug('Reviewing cert sign request')

        if not self.ca:
            raise ValueError('Only CAs review CSRs')

        if not csr.is_signature_valid:
            raise ValueError('CSR with invalid signature')

        sign_algo: str = csr.signature_algorithm_oid._name
        if sign_algo not in CaSecret.VALID_SIGNATURE_ALGORITHMS:
            raise ValueError(f'Invalid algorithm: {sign_algo}')

        if csr.signature_hash_algorithm:
            hash_algo: str = csr.signature_hash_algorithm.name
            if hash_algo not in CaSecret.VALID_SIGNATURE_HASHES:
                raise ValueError(f'Invalid algorithm: {hash_algo}')

        # We start parsing the Subject of the CSR, which
        # consists of a list of 'Relative' Distinguished Names
        distinguished_name: str = ','.join(
            [rdns.rfc4514_string() for rdns in csr.subject.rdns]
        )

        common_name: str = self.review_distinguishedname(distinguished_name)

        subject_name: str = self.review_subjectalternative_name(csr)

        if common_name != subject_name:
            raise ValueError(
                f'Common name {common_name} does not match '
                f'subject alternative name {subject_name}'
            )

        return common_name

    def review_subjectalternative_name(self, csr, max_dns_names: int = 1
                                       ) -> str:
        '''
        Extracts the subject alternative name extension of the CSR
        '''

        extention: x509.Extension = csr.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        )
        dnsnames: list[str] = extention.value.get_values_for_type(x509.DNSName)

        if not dnsnames:
            raise ValueError('CSR can not have no DNS names')

        if len(dnsnames) > max_dns_names:
            raise ValueError(
                f'Only {max_dns_names} DNSs name allow for '
                f'SubjectAlternativeName, found: {", ".join(dnsnames)}'
            )

        return dnsnames[0]

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
        bits: list[str] = name.split(',')
        for dn in bits:
            key: str
            value: str
            key, value = dn.split('=')
            if not key or not value:
                raise ValueError(f'Invalid commonname: {name}')
            if key in CaSecret.IGNORED_X509_NAMES:
                continue
            if key == 'CN':
                commonname: str = value
                return commonname
            else:
                raise ValueError(f'Unknown distinguished name: {key}')

        raise ValueError(f'commonname not found in {name}')

    @override
    def review_commonname(self, commonname: str, uuid_identifier=True,
                          check_service_id=True) -> EntityId:
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

        if check_service_id and self.service_id is None:
            raise ValueError(
                'No service_id set, while we want to check the service_id '
                f'in the commonname: {commonname}'
            )

        entity_id: EntityId = CaSecret.review_commonname_by_parameters(
            commonname,
            self.network,
            self.accepted_csrs,
            service_id=self.service_id,
            uuid_identifier=uuid_identifier,
            check_service_id=check_service_id
        )

        return entity_id

    @override
    @staticmethod
    def review_commonname_by_parameters(
            commonname: str, network: str, accepted_csrs: dict[IdType, int],
            service_id: int = None, uuid_identifier: bool = True,
            check_service_id: bool = True) -> EntityId:
        '''
        Reviews a common name without requiring an instance of the CA class to
        be created
        '''

        if service_id:
            service_id = int(service_id)

        entity_id: EntityId = Secret.review_commonname_by_parameters(
            commonname, network, service_id=service_id,
            uuid_identifier=uuid_identifier, check_service_id=check_service_id
        )

        if entity_id.id_type not in accepted_csrs:
            accepted_csr_values: list[str] = [
                csr.value for csr in accepted_csrs
            ]
            raise PermissionError(
                f'CA accepts CSRs for {", ".join(accepted_csr_values)} but '
                f'does not sign CSRs for subdomain {entity_id.id_type.value}'
            )

        return entity_id

    def sign_csr(self, csr: CSR, expire: int | timedelta | datetime = None
                 ) -> CertChain:
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

        if expire:
            if isinstance(expire, int):
                expiration: datetime = datetime.now(tz=UTC) + timedelta(
                    days=expire
                )
            elif isinstance(expire, datetime):
                expiration = expire
            elif isinstance(expire, timedelta):
                expiration: datetime = datetime.now(tz=UTC) + expire
            else:
                raise ValueError(
                    'expire must be an int, datetime or timedelta, not: '
                    f'{type(expire)}'
                )
        else:
            entity_id: EntityId = self.review_csr(csr, source=CsrSource.LOCAL)
            if entity_id.id_type not in self.accepted_csrs:
                raise ValueError(
                    f'We do not sign CSRs for entity type: {entity_id.id_type}'
                )
            expiration_days: int = self.accepted_csrs[entity_id.id_type]

            expiration: datetime = \
                datetime.now(tz=UTC) + timedelta(days=expiration_days)

        try:
            ca_extension: x509.Extension[x509.BasicConstraints] = \
                csr.extensions.get_extension_for_class(x509.BasicConstraints)
            is_ca: bool = ca_extension.value.ca
        except x509.ExtensionNotFound:
            is_ca = False

        try:
            keyusage_extension: x509.Extension[x509.KeyUsage] = \
                csr.extensions.get_extension_for_class(x509.KeyUsage)
        except x509.ExtensionNotFound:
            raise ValueError(
                'CSR does not have Key Usage Constraints extension'
            )

        ext_keyusage_extension: x509.Extension[x509.ExtendedKeyUsage]
        try:
            ext_keyusage_extension: x509.Extension[x509.ExtendedKeyUsage] = \
                csr.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        except x509.ExtensionNotFound:
            ext_keyusage_extension = None

        dnsname: str = self.review_subjectalternative_name(csr)

        _LOGGER.debug(f'Signing cert with cert {self.common_name}')

        cert_builder: x509.CertificateBuilder = x509.CertificateBuilder(
        ).subject_name(
            csr.subject
        ).issuer_name(
            self.cert.subject
        ).public_key(
            csr.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.now(tz=UTC)
        ).not_valid_after(
            expiration
        ).add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(dnsname)]
            ),
            critical=False
        ).add_extension(
            x509.BasicConstraints(
                ca=is_ca, path_length=None
            ), critical=True,
        ).add_extension(
            x509.SubjectKeyIdentifier.from_public_key(
                csr.public_key()
            ), critical=False
        ).add_extension(
            keyusage_extension.value, critical=True
        )

        if ext_keyusage_extension:
            cert_builder = cert_builder.add_extension(
                ext_keyusage_extension.value, critical=False
            )

        if not self.is_root_cert:
            cert_builder = cert_builder.add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    self.private_key.public_key()
                ), critical=False
            )

        cert: x509.Certificate = cert_builder.sign(
            self.private_key, hashes.SHA256()
        )

        cert_chain = []
        if not self.is_root_cert:
            cert_chain: list[x509.Certificate] = [deepcopy(self.cert)]

        if self.cert_chain:
            cert_chain.extend(deepcopy(self.cert_chain))

        return CertChain(cert, cert_chain)
