'''
Cert manipulation

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import re
import logging
import tempfile
import subprocess

from uuid import UUID
from typing import TypeVar
from datetime import datetime
from datetime import timedelta
from urllib.parse import urlparse
from urllib.parse import ParseResult

import ssl
import aiohttp
import asyncio

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.x509 import Certificate
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from certvalidator import CertificateValidator
from certvalidator import ValidationContext
from certvalidator import ValidationError, PathBuildingError

from byoda.storage.filestorage import FileStorage, FileMode

from byoda.datatypes import IdType
from byoda.datatypes import EntityId

from byoda.util.paths import Paths

from byoda import config

from .certchain import CertChain

_LOGGER = logging.getLogger(__name__)

_RSA_KEYSIZE = 3072

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

CaSecret = TypeVar('CaSecret')
Server = TypeVar('Server')


class Secret:
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

    __slots__ = [
        'private_key', 'private_key_file', 'cert', 'cert_file', 'paths',
        'password', 'common_name', 'service_id', 'id_type', 'sans',
        'storage_driver', 'cert_chain', 'is_root_cert', 'ca',
        'signs_ca_certs', 'max_path_length', 'accepted_csrs'
    ]

    # When should the secret be renewed
    RENEW_WANTED = datetime.now() + timedelta(days=90)
    RENEW_NEEDED: datetime = datetime.now() + timedelta(days=30)

    # We don't sign any CSRs as we are not a CA
    ACCEPTED_CSRS = None

    def __init__(self, cert_file: str = None, key_file: str = None,
                 storage_driver: FileStorage = None):
        '''
        Constructor

        :param cert_file: string with the path to the certificate file
        :param key_file: string with the path to the key file. If supplied
        :returns: (none)
        :raises: (none)
        '''

        self.private_key: rsa.RSAPrivateKey = None
        self.private_key_file: str = key_file

        self.cert: Certificate = None
        self.cert_file: str = cert_file

        # Some derived classes already set self.paths before
        # calling super().__init__() so we don't want to overwrite
        # that
        if not hasattr(self, 'paths'):
            self.paths: Paths | None = None

        # The password to use for saving the private key
        # to a file
        self.password: str = None

        self.common_name: str = None
        self.service_id: str | None = None
        self.id_type: IdType = None

        # Subject Alternative Name, usually same as common name
        # except for App Data certs
        self.sans: list[str] = None

        if storage_driver:
            self.storage_driver: FileStorage = storage_driver

        # Certchains never include the root cert!
        # Certs higher in the certchain hierarchy come after
        # certs signed by those certs.
        self.cert_chain: list[Certificate] = []

        # Is this a self-signed cert?
        self.is_root_cert: bool = False

        # X.509 constraints
        # is this a secret of a CA. For CAs, use the CaSecret class
        self.ca: bool = False
        self.signs_ca_certs: bool = False
        self.max_path_length: int = None

        self.accepted_csrs: dict[IdType, int] = ()

    async def create(self, common_name: str, issuing_ca: CaSecret = None,
                     expire: int = None, key_size: int = _RSA_KEYSIZE,
                     private_key: rsa.RSAPrivateKey = None, ca: bool = False):
        '''
        Creates an RSA private key and either a self-signed X.509 cert
        or a cert signed by the issuing_ca. The latter is a one-step
        process if you have access to the private key of the issuing CA

        :param common_name: common_name for the certificate
        :param issuing_ca: optional, CA to sign the cert with. If not provided,
        a self-signed cert will be created
        :param expire: days after which the cert should expire, only used
        for self-signed certs
        :param key_size: length of the key in bits
        :param ca: create a secret for an CA
        :returns: (none)
        :raises: ValueError if the Secret instance already has a private key
        or set
        '''

        if self.private_key or self.cert:
            raise ValueError('Secret already has a key and cert')

        if not self.is_root_cert and not issuing_ca:
            raise ValueError('Only root certs should be self-signed')

        self.common_name = common_name
        self.ca = ca or self.ca

        _LOGGER.debug(
            f'Generating a private key with key size {key_size}, '
            f'expiration {expire}  and commonname {common_name} '
            f'with CA is {self.ca}'
        )

        if private_key:
            self.private_key = private_key
        else:
            self.private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=key_size
            )

        if issuing_ca:
            # TODO: SECURITY: add constraints
            csr = await self.create_csr(ca)
            self.cert = issuing_ca.sign_csr(csr)
        else:
            self.create_selfsigned_cert(expire, ca)

    def create_selfsigned_cert(self,
                               expire: int | datetime | timedelta = 10950,
                               ca: bool = False):
        '''
        Create a self_signed certificate. Self-signed certs have
        a expiration of 30 years by default

        :param expire: number of days after which the cert should expire,
        either as int or timedelta or the date when the cert should expire
        as datetime

        :param bool: is the cert for a CA?
        :returns: (none)
        :raises: (none)
        '''

        subject = issuer = self._generate_cert_name()

        if expire:
            if isinstance(expire, int):
                expiration: datetime = datetime.utcnow() + timedelta(
                    days=expire
                )
            elif isinstance(expire, datetime):
                expiration = expire
            elif isinstance(expire, timedelta):
                expiration: datetime = datetime.utcnow() + expire
            else:
                raise ValueError(
                    'expire must be an int, datetime or timedelta, not: '
                    f'{type(expire)}'
                )
        else:
            expiration: datetime = datetime.utcnow() + timedelta(days=3650)

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
            datetime.utcnow()
        ).not_valid_after(
            expiration
        ).add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(self.common_name)]
            ),
            critical=False
        ).add_extension(
            x509.BasicConstraints(
                ca=ca, path_length=None
            ), critical=True,
        ).sign(self.private_key, hashes.SHA256())

    async def create_csr(self, common_name: str, sans: str | list[str] = [],
                         key_size: int = _RSA_KEYSIZE, ca: bool = False,
                         renew: bool = False) -> CSR:
        '''
        Creates an RSA private key and a CSR. After calling this function,
        you can call Secret.get_csr_signature(issuing_ca) afterwards to
        generate the signed certificate

        :param common_name: common_name for the certificate
        :param key_size: length of the key in bits
        :param ca: create a secret for an CA
        :param renew: should any existing private key be used to
        renew an existing certificate
        :returns: the Certificate Signature Request
        :raises: ValueError if the Secret instance already has a private key
                 or set
        '''

        if (self.private_key or self.cert) and not renew:
            raise ValueError('Secret already has a cert or private key')

        # TODO: SECURITY: add constraints
        self.common_name = common_name
        self.sans = [common_name]
        if sans:
            if isinstance(sans, list):
                self.sans.extend(sans)
            elif isinstance(sans, str):
                self.sans.append(sans)
            else:
                raise ValueError('sans parameter must be a list or str')

        _LOGGER.debug(
            f'Generating a private key with key size {key_size} '
            f'and commonname {self.common_name}'
        )

        if renew:
            if not self.private_key:
                await self.load(with_private_key=True)
        else:
            self.private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=_RSA_KEYSIZE,
            )

        _LOGGER.debug(f'Generating a CSR for {self.common_name}')

        san_names = []
        for san in self.sans:
            san_names.append(x509.DNSName(san))

        csr_builder = x509.CertificateSigningRequestBuilder().subject_name(
            self._generate_cert_name()
        ).add_extension(
            x509.BasicConstraints(
                ca=ca, path_length=self.max_path_length
            ), critical=True,
        ).add_extension(
            x509.SubjectAlternativeName(san_names),
            critical=True
        )

        csr = csr_builder.sign(self.private_key, hashes.SHA256())

        return csr

    def _generate_cert_name(self):
        '''
        Generate an X509.Name instance for a cert

        :param  : (none)
        :returns: (none)
        :raises: (none)
        '''

        return x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, u'SW'),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u'SW'),
                x509.NameAttribute(NameOID.LOCALITY_NAME, u'local'),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, u'memyselfandi'),
                x509.NameAttribute(NameOID.COMMON_NAME, str(self.common_name))
            ]
        )

    @staticmethod
    def extract_commonname(cert: x509.Certificate) -> str:
        '''
        Extracts the common name from a the subject of a certificate
        '''

        for attrib in cert.subject:
            if attrib.oid == NameOID.COMMON_NAME:
                commonname = attrib.value

        return commonname

    def csr_as_pem(self, csr) -> str:
        '''
        Returns the BASE64 encoded byte string for the CSR

        :returns: bytes with the PEM-encoded certificate
        :raises: (none)
        '''
        return csr.public_bytes(serialization.Encoding.PEM).decode('utf-8')

    async def get_csr_signature(self, csr: CSR, issuing_ca, expire: int = 365):
        '''
        Gets the cert signed and adds the signed cert to the secret

        :param csr: the certificate signature request
        :param Secret issuing_ca: Certificate to sign the CSR with
        :returns: (none)
        :raises: (none)
        '''

        _LOGGER.debug(
            f'Getting CSR with common name {self.common_name} signed'
        )
        self.from_signed_cert(issuing_ca.sign_csr(csr, expire=expire))
        await self.save(password=self.password)

    def from_signed_cert(self, cert_chain: CertChain):
        '''
        Adds the CA-signed cert and the certchain with the issuing CA
        to the certificate

        :param CertChain cert_chain: cert and its chain of issuing CAs
        :returns: (none)
        :raises: (none)
        '''

        self.cert = cert_chain.signed_cert
        self.cert_chain = cert_chain.cert_chain

    def validate(self, root_ca: CaSecret, with_openssl: bool = False):
        '''
        Validate that the cert and its certchain are anchored to the root cert.
        This function does not check certificate recovation or OCSP

        :param Secret root_ca: the self-signed root CA to validate against
        :param with_openssl: also use the openssl binary to validate the cert
        :returns: (none)
        :raises: ValueError if the certchain is invalid
        '''

        pem_signed_cert = self.cert_as_pem()
        pem_cert_chain = [
            cert.public_bytes(serialization.Encoding.PEM)
            for cert in self.cert_chain
        ]
        context = ValidationContext(
            trust_roots=[root_ca.cert_as_pem()]
        )
        validator = CertificateValidator(
            pem_signed_cert, pem_cert_chain, validation_context=context
        )
        try:
            validator.validate_usage(set())
        except (ValidationError, PathBuildingError) as exc:
            raise ValueError(f'Certchain failed validation: {exc}') from exc

        if not with_openssl:
            return

        tmpdir = tempfile.TemporaryDirectory()
        rootfile = tmpdir.name + '/rootca.pem'
        with open(rootfile, 'w') as file_desc:
            file_desc.write(root_ca.cert_as_pem().decode('utf-8'))

        certfile = tmpdir.name + '/cert.pem'
        with open(certfile, 'w') as file_desc:
            file_desc.write(self.cert_as_pem().decode('utf-8'))

        cmd = [
            'openssl', 'verify',
            '-CAfile', rootfile,
        ]

        if self.cert_chain:
            chainfile = tmpdir.name + '/chain.pem'
            with open(chainfile, 'w') as file_desc:
                for cert in self.cert_chain:
                    file_desc.write(
                        cert.public_bytes(
                            serialization.Encoding.PEM
                        ).decode('utf-8')
                    )
            cmd.extend(['-untrusted', chainfile])

        cmd.append(certfile)
        result = subprocess.run(cmd)

        if result.returncode != 0:
            raise ValueError(
                f'Certificate validation with command {" ".join(cmd)} '
                f'failed: {result.returncode} for cert {certfile} and '
                f'root CA {rootfile}'
            )

        tmpdir.cleanup()

        _LOGGER.debug(
            'Successfully validated certchain using OpenSSL for '
            f'cert {certfile} and root CA {rootfile}'
        )

    async def cert_file_exists(self) -> bool:
        '''
        Checks whether the file with the cert of the secret exists

        :returns: bool
        '''

        return await self.storage_driver.exists(self.cert_file)

    async def private_key_file_exists(self) -> bool:
        '''
        Checks whether the file with the cert of the secret exists

        :returns: bool
        '''

        return await self.storage_driver.exists(self.private_key_file)

    async def load(self, with_private_key: bool = True,
                   password: str = 'byoda',
                   storage_driver: FileStorage = None):
        '''
        Load a cert and private key from their respective files. The
        certificate file can include a cert chain. The cert chain should
        be in order from leaf cert to the highest cert in the chain.

        :param with_private_key: should private key be read for this cert
        :param password: password to decrypt the private_key
        :returns: (none)
        :raises: ValueError if a certificate or private key is already
                available in the secret FileNotFoundError if the certificate
                file or the file with the private key do not exist
        '''

        if not storage_driver:
            storage_driver = self.storage_driver

        # We allow (re-)loading an existing secret if we do not have
        # the private key and we need to read the private key.
        if self.private_key or (self.cert and not with_private_key):
            raise ValueError(
                'Secret already has certificate and/or private key'
            )

        if await self.storage_driver.exists(self.cert_file):
            cert_data = await self.storage_driver.read(self.cert_file)
            _LOGGER.debug(
                f'Loading cert from {self.cert_file}, '
                f'got {len(cert_data)} bytes'
            )
        else:
            raise FileNotFoundError(f'cert file not found: {self.cert_file}')

        self.from_string(cert_data)

        try:
            extension = self.cert.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
            self.ca = extension.value.ca
        except x509.ExtensionNotFound:
            self.ca = False

        if with_private_key:
            # Only croak about expiration of cert if we own the private key
            if self.cert.not_valid_after < self.RENEW_WANTED:
                # TODO: add logic to recreate the signed cert
                if self.cert.not_valid_after < self.RENEW_NEEDED:
                    _LOGGER.warning(
                        f'Certificate {self.cert_file} expires in 30 days: '
                        f'{self.RENEW_NEEDED}'
                    )
                else:
                    _LOGGER.info(
                        f'Certificate {self.cert_file} expires in 90 days: '
                        f'{self.RENEW_WANTED}'
                    )

        self.common_name = None
        for rdns in self.cert.subject.rdns:
            dn = rdns.rfc4514_string()
            if dn.startswith('CN='):
                self.common_name = dn[3:]
                break

        self.private_key = None
        if with_private_key:
            try:
                _LOGGER.debug(
                    f'Reading private key from {self.private_key_file}'
                )
                data = await self.storage_driver.read(
                    self.private_key_file, file_mode=FileMode.BINARY
                )

                self.private_key = serialization.load_pem_private_key(
                    data, password=str.encode(password)
                )
            except FileNotFoundError:
                _LOGGER.exception(
                    f'CA private key file not found: {self.private_key_file}'
                )
                raise

    def from_string(self, cert: str, certchain: str = None):
        '''
        Loads an X.509 cert and certchain from a string. If the cert has an
        certchain then the certchain can either be included at the end
        of the string of the cert or can be provided as a separate parameter

        :param cert: the base64-encoded cert
        :param certchain: the base64-encoded certchain
        :returns: (none)
        :raises: (none)
        '''

        if isinstance(cert, bytes):
            cert = cert.decode('utf-8')

        if certchain:
            if isinstance(certchain, bytes):
                certchain = certchain.encode('utf-8')
            cert = cert + certchain

        # The re.split results in one extra
        certs = re.findall(
            r'^-+BEGIN\s+CERTIFICATE-+[^-]*-+END\s+CERTIFICATE-+$',
            cert, re.MULTILINE
        )

        if len(certs) == 0:
            raise ValueError(f'No cert found in {cert}')
        elif len(certs) == 1:
            self.cert = x509.load_pem_x509_certificate(
                str.encode(certs[0])
            )
        elif len(certs) > 1:
            self.cert = x509.load_pem_x509_certificate(
                str.encode(certs[0])
            )
            self.cert_chain = [
                x509.load_pem_x509_certificate(
                    str.encode(cert_data)
                )
                for cert_data in certs[1:]
            ]

    @staticmethod
    def csr_from_string(csr: str) -> x509.CertificateSigningRequest:
        '''
        Converts a string to a X.509 CSR

        :param csr: the base64-encoded CSR
        :returns: an X509-encoded CSR
        :raises: (none)
        '''

        if isinstance(csr, str):
            csr = str.encode(csr)

        return x509.load_pem_x509_csr(csr)

    async def save(self, password: str = 'byoda', overwrite: bool = False,
                   storage_driver: FileStorage = None):
        '''
        Save a cert and private key (if we have it) to their respective files

        :param password: password to decrypt the private_key
        :param overwrite: should any existing files be overwritten
        :param storage_driver: the storage driver to use
        :returns: (none)
        :raises: PermissionError if the file for the cert and/or key
        already exist and overwrite == False
        '''

        if not storage_driver:
            storage_driver = self.storage_driver

        if not overwrite and await storage_driver.exists(self.cert_file):
            raise PermissionError(
                f'Can not save cert because the certificate '
                f'already exists at {self.cert_file}'
            )

        _LOGGER.debug(
            f'Saving cert to {self.cert_file} with fingerprint '
            f'{self.cert.fingerprint(hashes.SHA256()).hex()} '
        )
        data = self.certchain_as_pem()

        await storage_driver.create_directory(self.cert_file)

        await storage_driver.write(
            self.cert_file, data, file_mode=FileMode.BINARY
        )

        if self.private_key:
            await self.save_private_key(
                password=password, overwrite=overwrite,
                storage_driver=storage_driver
            )

    async def save_private_key(self, password: str = 'byoda',
                               overwrite: bool = False,
                               storage_driver: FileStorage = None):
        '''
        Save a private key (if we have it) to their respective files

        :param password: password to decrypt the private_key
        :param overwrite: should any existing files be overwritten
        :param storage_driver: the storage driver to use
        :returns: (none)
        :raises: PermissionError if the file for the cert and/or key
        already exist and overwrite == False
        '''
        if not storage_driver:
            storage_driver = self.storage_driver

        if (not overwrite and self.private_key
                and await storage_driver.exists(self.private_key_file)):
            raise PermissionError(
                f'Can not save the private key because the key already '
                f'exists at {self.private_key_file}'
            )

        if self.private_key:
            _LOGGER.debug(f'Saving private key to {self.private_key_file}')
            private_key_pem = self.private_key_as_bytes(password)
            await storage_driver.write(
                self.private_key_file, private_key_pem,
                file_mode=FileMode.BINARY
            )

    def private_key_as_bytes(self, password: str = None) -> bytes:
        if password:
            private_key_pem = self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.BestAvailableEncryption(
                    str.encode(password)
                )
            )
        else:
            private_key_pem = self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )

        return private_key_pem

    def private_key_as_pem(self, password: str = None) -> str:
        '''
        Returns the private key in PEM format
        '''

        private_key_bytes = self.private_key_as_bytes(password)
        return private_key_bytes.decode('utf-8')

    def certchain_as_pem(self) -> str:
        '''
        :returns: the certchain as a str
        '''

        data = bytes()
        for cert in [self.cert] + self.cert_chain:
            cert_info = (
                f'# Issuer {cert.issuer}\n'
                f'# Subject {cert.subject}\n'
                f'# Valid from {cert.not_valid_before} to '
                f'{cert.not_valid_after}\n'
            )
            data += str.encode(cert_info)
            data += cert.public_bytes(serialization.Encoding.PEM)

        return data.decode('utf-8')

    def cert_as_pem(self) -> bytes:
        '''
        Returns the BASE64 encoded byte string for the certificate

        :returns: bytes with the PEM-encoded certificate
        :raises: (none)
        '''
        return self.cert.public_bytes(serialization.Encoding.PEM)

    def fingerprint(self) -> bytes:
        '''
        Returns the SHA256 fingerprint of the certificate
        '''

        return self.cert.fingerprint(hashes.SHA256())

    def save_tmp_private_key(self, filepath: str = '/var/tmp/private.key'
                             ) -> str:
        '''
        Create an unencrypted copy of the key to the /tmp directory
        so both the requests library and nginx can read it

        :returns: filename to which the key was saved
        :raises: (none)
        '''

        # private key is used both by nginx server and requests client

        _LOGGER.debug('Saving private key to %s', filepath)

        private_key_pem = self.private_key_as_pem()
        with open(filepath, 'w') as file_desc:
            file_desc.write(private_key_pem)

        return filepath

    def get_tmp_private_key_filepath(self,
                                     filepath: str = '/var/tmp/private.key'
                                     ) -> str:
        '''
        Gets the location where on local storage the unprotected private
        key is stored
        '''

        return filepath

    def review_commonname(self, commonname: str, uuid_identifier=True,
                          check_service_id=True) -> str:
        '''
        Checks if the structure of common name matches that of a byoda secret.
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

        service_id = getattr(self, 'service_id', None)

        entity_id = Secret.review_commonname_by_parameters(
            commonname,
            self.network,
            service_id=service_id,
            uuid_identifier=uuid_identifier,
            check_service_id=check_service_id
        )

        return entity_id

    @staticmethod
    def review_commonname_by_parameters(
            commonname: str, network: str,
            service_id: int = None, uuid_identifier: bool = True,
            check_service_id: bool = True) -> EntityId:
        '''
        Basic review for a common name

        :returns: the common name with the domain name chopped off
        :raises: ValueError
        '''

        _LOGGER.debug(f'Reviewing common name: {commonname}')

        if not isinstance(commonname, str):
            raise ValueError(
                f'Common name must be of type str, not {type(commonname)}'
            )

        if check_service_id and service_id is None:
            raise ValueError(
                'Can not check service_id as no service_id was provided'
            )

        hostname, subdomain, domain = commonname.split('.', 2)
        if not (hostname and subdomain and domain):
            raise ValueError(f'Invalid common name: {commonname}')

        if not commonname.endswith('.' + network):
            raise PermissionError(
                f'Commonname {commonname} is not for network {network}'
            )

        commonname_prefix = commonname[:-(len(network) + 1)]

        bits = commonname_prefix.split('.')
        if len(bits) > 2:
            raise ValueError(f'Invalid number of domain levels: {commonname}')
        elif len(bits) == 2:
            identifier, subdomain = bits
        else:
            identifier = None
            subdomain = bits[0]

        if uuid_identifier:
            try:
                identifier = UUID(identifier)
            except ValueError:
                raise ValueError(
                    f'Common name {commonname} does not have a valid UUID '
                    'identifier'
                )

        # We have subdomains like 'account', 'member-123', 'network-data' and
        # 'service-ca-123'
        # We first want to check if the last segment is a number
        cn_service_id = None
        bits = subdomain.split('-')
        if len(bits) > 1:
            cn_service_id = bits[-1]
            try:
                cn_service_id = int(cn_service_id)
                subdomain = '-'.join(bits)[:-1]
            except ValueError:
                cn_service_id = None
                if check_service_id:
                    raise ValueError(
                        f'Invalid service id in subdomain {subdomain}'
                    )

        _LOGGER.debug('Common name for service id %s', cn_service_id)
        if (cn_service_id is not None
                and (cn_service_id < 0 or cn_service_id > (pow(2, 32) - 1))):
            raise ValueError(
                f'Service ID {cn_service_id} out of range in '
                f'{commonname}'
            )

        id_type = None
        for id_type_iter in IdType.by_value_lengths():
            if (subdomain.startswith(id_type_iter.value.rstrip('-'))):
                id_type = id_type_iter
                break

        _LOGGER.debug(f'Found IdType {id_type}')
        if not id_type:
            raise ValueError(
                f'Commonname {commonname} is not for a known certificate type'
            )

        if check_service_id and cn_service_id != service_id:
            raise PermissionError(
                f'Request for incorrect service {cn_service_id} in common '
                f'name {commonname}'
            )

        return EntityId(id_type, identifier, cn_service_id)

    @staticmethod
    async def download(url: str, root_ca_filepath: str | None = None,
                       network_name: str | None = None) -> str | None:
        '''
        Downloads the secret from the given URL

        :param url:
        :param root_ca_filepath: path (starting with '/') to the root CA file
        :param network_name:
        :returns Secret : the downloaded data secret as a string
        :raises: (none)
        '''

        _LOGGER.debug(f'Downloading secret from {url}')

        try:
            # FIXME: needs clean solution do get cert from test case
            if (config.debug and hasattr(config, 'tls_cert_file')
                    and 'aaaaaaaa' in url):
                with open(config.tls_cert_file, 'rb') as file_desc:
                    cert_data = file_desc.read()
            else:
                parsed_url: ParseResult = urlparse(url)
                if (parsed_url.hostname.startswith('dir.')
                        or parsed_url.hostname.startswith('proxy.')
                        or (network_name
                            and network_name not in parsed_url.hostname)):
                    ssl_context = None
                else:
                    ssl_context = ssl.create_default_context(
                        cafile=root_ca_filepath
                    )
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, ssl=ssl_context) as response:
                        if response.status >= 400:
                            raise RuntimeError(
                                f'Failure to GET {url}: {response.status}'
                            )

                        cert_data = await response.text()
            return cert_data
        except (aiohttp.ServerTimeoutError, aiohttp.ServerConnectionError,
                aiohttp.client_exceptions.ClientConnectorCertificateError,
                aiohttp.client_exceptions.ClientConnectorError,
                asyncio.exceptions.TimeoutError) as exc:
            _LOGGER.info(f'Failed to GET {url}: {exc}')
            raise RuntimeError(f'Could not GET {url}: {exc}')
