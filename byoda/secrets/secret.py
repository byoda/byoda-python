'''
Cert manipulation

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import os
import logging
import datetime
import re
import tempfile
import subprocess
from uuid import UUID
from copy import copy
from typing import TypeVar, List

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.x509 import Certificate
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import utils

from certvalidator import CertificateValidator
from certvalidator import ValidationContext
from certvalidator import ValidationError, PathBuildingError

from byoda.storage.filestorage import FileStorage, FileMode

from byoda.datatypes import IdType
from byoda.datatypes import EntityId

from .certchain import CertChain

_LOGGER = logging.getLogger(__name__)

_RSA_KEYSIZE = 3072
_RSA_SIGN_MAX_MESSAGE_LENGTH = 1024

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

CaSecret = TypeVar('CaSecret')


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

        # There is no default location for this file.
        self.unencrypted_private_key_file: str = None

        self.cert: Certificate = None
        self.cert_file: str = cert_file

        # The password to use for saving the private key
        # to a file
        self.password: str = None

        self.common_name: str = None

        if storage_driver:
            self.storage_driver: FileStorage = storage_driver

        # Certchains never include the root cert!
        # Certs higher in the certchain hierarchy come after
        # certs signed by those certs.
        self.cert_chain: List[Certificate] = []

        # Is this a self-signed cert?
        self.is_root_cert: bool = False

        # X.509 constraints
        # is this a secret of a CA. For CAs, use the CaSecret class
        self.ca: bool = False
        self.max_path_length: int = None

    def create(self, common_name: str, issuing_ca: CaSecret = None,
               expire: int = 30, key_size: int = _RSA_KEYSIZE,
               ca: bool = False):
        '''
        Creates an RSA private key and either a self-signed X.509 cert
        or a cert signed by the issuing_ca. The latter is a one-step
        process if you have access to the private key of the issuing CA

        :param common_name: common_name for the certificate
        :param issuing_ca: optional, CA to sign the cert with. If not provided,
        a self-signed cert will be created
        :param expire: days after which the cert should expire
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
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=key_size
        )

        if issuing_ca:
            # TODO: SECURITY: add constraints
            csr = self.create_csr(ca)
            self.cert = issuing_ca.sign_csr(csr, expire)
        else:
            self.create_selfsigned_cert(expire, ca)

    def create_selfsigned_cert(self, expire=365, ca=False):
        '''
        Create a self_signed certificate

        :param expire: days after which the cert should expire
        :param bool: is the cert for a CA
        :returns: (none)
        :raises: (none)
        '''

        subject = issuer = self._get_cert_name()

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
            x509.SubjectAlternativeName(
                [x509.DNSName(self.common_name)]
            ),
            critical=False
        ).add_extension(
            x509.BasicConstraints(
                ca=ca, path_length=None
            ), critical=True,
        ).sign(self.private_key, hashes.SHA256())

    def create_csr(self, common_name: str, key_size: int = _RSA_KEYSIZE,
                   ca: bool = False) -> CSR:
        '''
        Creates an RSA private key and a CSR. After calling this function,
        you can call Secret.get_csr_signature(issuing_ca) afterwards to
        generate the signed certificate

        :param common_name: common_name for the certificate
        :param key_size: length of the key in bits
        :param ca: create a secret for an CA
        :returns: the Certificate Signature Request
        :raises: ValueError if the Secret instance already has a private key
                 or set
        '''

        if self.private_key or self.cert:
            raise ValueError('Secret already has a cert or private key')

        # TODO: SECURITY: add constraints
        self.common_name = common_name

        _LOGGER.debug(
            f'Generating a private key with key size {key_size} '
            f'and commonname {common_name}'
        )

        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=_RSA_KEYSIZE,
        )

        _LOGGER.debug(f'Generating a CSR for {self.common_name}')

        csr = x509.CertificateSigningRequestBuilder().subject_name(
            self._get_cert_name()
        ).add_extension(
            x509.BasicConstraints(
                ca=ca, path_length=self.max_path_length
            ), critical=True,
        ).add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(self.common_name)]
            ),
            critical=False
        ).sign(self.private_key, hashes.SHA256())

        return csr

    def _get_cert_name(self):
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

    def csr_as_pem(self, csr):
        '''
        Returns the BASE64 encoded byte string for the CSR

        :returns: bytes with the PEM-encoded certificate
        :raises: (none)
        '''
        return csr.public_bytes(serialization.Encoding.PEM)

    def get_csr_signature(self, csr: CSR, issuing_ca, expire: int = 365):
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
        self.save(password=self.password)

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
            x.public_bytes(serialization.Encoding.PEM)
            for x in self.cert_chain
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

    def sign_message(self, message: str, hash_algorithm: str = 'SHA256'
                     ) -> bytes:
        '''
        Sign a message message

        :returns: signature for the message
        :raises: ValueError, NotImplementedError
        '''

        if isinstance(message, str):
            message = message.encode('utf-8')
        elif not isinstance(message, bytes):
            raise ValueError(
                f'Message must be of type string or bytes, not {type(message)}'
            )

        chosen_hash = hashes.SHA256()

        digest = Secret._get_digest(message, chosen_hash)

        signature = self.private_key.sign(
            digest,
            padding.PSS(
                mgf=padding.MGF1(chosen_hash),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            utils.Prehashed(chosen_hash)
        )

        return signature

    def verify_message_signature(self, message: str, signature: bytes,
                                 hash_algorithm: str = 'SHA256') -> None:
        '''
        Verify the signature for a message

        :raises: InvalidSignature if the signature is invalid, ValueError
                 if the input is invalid
        '''

        if isinstance(message, str):
            message = message.encode('utf-8')
        elif not isinstance(message, bytes):
            raise ValueError(
                f'Message must be of type string or bytes, not {type(message)}'
            )

        if hash_algorithm != 'SHA256':
            raise NotImplementedError(
                'Only SHA256 is supported as hash algorithm'
            )

        chosen_hash = hashes.SHA256()
        digest = Secret._get_digest(message, chosen_hash)

        self.cert.public_key().verify(
            signature,
            digest,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            utils.Prehashed(chosen_hash)
        )

    @staticmethod
    def _get_digest(message: bytes, chosen_hash: hashes) -> bytes:
        '''
        Generates a digest hash for any length of message
        '''

        hasher = hashes.Hash(chosen_hash)
        message = copy(message)
        while message:
            if len(message) > _RSA_SIGN_MAX_MESSAGE_LENGTH:
                hasher.update(message[:_RSA_SIGN_MAX_MESSAGE_LENGTH])
                message = message[_RSA_SIGN_MAX_MESSAGE_LENGTH:]
            else:
                hasher.update(message)
                message = None
        digest = hasher.finalize()

        return digest

    def cert_file_exists(self) -> bool:
        '''
        Checks whether the file with the cert of the secret exists

        :returns: bool
        '''

        return self.storage_driver.exists(self.cert_file)

    def private_key_file_exists(self) -> bool:
        '''
        Checks whether the file with the cert of the secret exists

        :returns: bool
        '''

        self.storage_driver.exists(self.private_key_file)

    def load(self, with_private_key: bool = True, password: str = 'byoda'):
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

        # We allow (re-)loading an existing secret if we do not have
        # the private key and we need to read the private key.
        if self.private_key or (self.cert and not with_private_key):
            raise ValueError(
                'Secret already has certificate and/or private key'
            )

        try:
            _LOGGER.debug('Loading cert from %s', self.cert_file)
            cert_data = self.storage_driver.read(self.cert_file)
        except FileNotFoundError:
            _LOGGER.exception(f'cert file not found: {self.cert_file}')
            raise

        self.from_string(cert_data)

        try:
            extension = self.cert.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
            self.ca = extension.value.ca
        except x509.ExtensionNotFound:
            self.ca = False

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
                data = self.storage_driver.read(
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
        :param certchain: the
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
            raise ValueError(f'No cert found in {self.cert_file}')
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

    def save(self, password: str = 'byoda', overwrite: bool = False):
        '''
        Save a cert and private key to their respective files

        :param password: password to decrypt the private_key
        :param overwrite: should any existing files be overwritten
        :returns: (none)
        :raises: PermissionError if the file for the cert and/or key
        already exist and overwrite == False
        '''

        if not overwrite and self.storage_driver.exists(self.cert_file):
            raise PermissionError(
                f'Can not save cert because the certificate '
                f'already exists at {self.cert_file}'
            )
        if (not overwrite and self.private_key
                and self.storage_driver.exists(self.private_key_file)):
            raise PermissionError(
                f'Can not save the private key because the key already '
                f'exists at {self.private_key_file}'
            )

        _LOGGER.debug('Saving cert to %s', self.cert_file)
        data = self.certchain_as_pem()

        directory = os.path.dirname(self.cert_file)
        self.storage_driver.create_directory(directory)

        self.storage_driver.write(
            self.cert_file, data, file_mode=FileMode.BINARY
        )

        if self.private_key:
            _LOGGER.debug('Saving private key to %s', self.private_key_file)
            private_key_pem = self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.BestAvailableEncryption(
                    str.encode(password)
                )
            )

            self.storage_driver.write(
                self.private_key_file, private_key_pem,
                file_mode=FileMode.BINARY
            )

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

    def save_tmp_private_key(self, filepath: str = '/tmp/private.key') -> str:
        '''
        Create an unencrypted copy of the key to the /tmp directory
        so both the requests library and nginx can read it

        :returns: filename to which the key was saved
        :raises: (none)
        '''

        # private key is used both by nginx server and requests client
        _LOGGER.debug('Saving private key to %s', filepath)

        private_key_pem = self.private_key_as_pem()
        with open(filepath, 'wb') as file_desc:
            file_desc.write(private_key_pem)

        self.unencrypted_private_key_file = filepath

        return filepath

    def private_key_as_pem(self) -> bytes:
        '''
        Returns the private key in PEM format
        '''

        private_key_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        return private_key_pem

    def cert_as_pem(self):
        '''
        Returns the BASE64 encoded byte string for the certificate

        :returns: bytes with the PEM-encoded certificate
        :raises: (none)
        '''
        return self.cert.public_bytes(serialization.Encoding.PEM)

    def fingerprint(self):
        '''
        Returns the SHA256 fingerprint of the certificate
        '''

        return self.cert.fingerprint(hashes.SHA256)

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
