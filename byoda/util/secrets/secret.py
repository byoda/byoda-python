'''
Cert manipulation

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import os
import datetime
import logging
import re
from copy import copy

from cryptography import x509
from cryptography.x509 import Certificate
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization
from cryptography.fernet import Fernet

from certvalidator import CertificateValidator
from certvalidator import ValidationContext
from certvalidator import ValidationError

from byoda.storage.filestorage import FileStorage, FileMode

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


class CertChain:
    def __init__(self, signed_cert: Certificate, cert_chain
                 ):
        '''
        Represents a signed cert and the list of certs of issuing CAs
        that signed the cert. Does not include the root cert.

        :param X509 signed_cert : the signed cert
        :param list cert_chain  : the list of certs in the cert chain,
        excluding the signed cert
        :returns: (none)
        :raises: (none)
        '''

        self.signed_cert = signed_cert
        self.cert_chain = cert_chain

    def __str__(self) -> str:
        '''
        :returns: the certchain as a bytes array
        '''

        data = self.cert_as_string() + self.cert_chain_as_string()
        return data

    def as_dict(self) -> dict:
        '''

        :returns: {'cert': cert, 'certchain': certchain}
        '''
        return {
            'signed_cert': self.cert_as_string(),
            'cert_chain': self.cert_chain_as_string()
        }

    def cert_chain_as_string(self) -> str:
        data = ''
        for cert in self.cert_chain:
            data += self.cert_as_string(cert)

        return data

    def cert_as_string(self, cert: Certificate = None) -> str:
        if not cert:
            cert = self.signed_cert

        cert_info = (
            f'# Issuer {cert.issuer}\n'
            f'# Subject {cert.subject}\n'
            f'# Valid from {cert.not_valid_before} to {cert.not_valid_after}\n'
        )
        data = cert_info
        data += cert.public_bytes(serialization.Encoding.PEM).decode('utf-8')
        data += '\n'

        return data


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

        self.private_key = None
        self.private_key_file = key_file
        self.cert = None
        self.cert_file = cert_file
        self.password = None
        self.common_name = None
        self.is_root_cert = False
        self.ca = False
        self.storage_driver = storage_driver

        # Certchains never include the root cert!
        # Certs higher in the certchain come before
        # certs signed by those certs
        self.cert_chain = []

        self.shared_key = None
        self.protected_shared_key = None

    def create(self, common_name: str, issuing_ca: bool = None,
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
            csr = self.create_csr(ca)
            self.cert = issuing_ca.sign_csr(csr, expire)
        else:
            self.create_selfsigned_cert(expire, ca)

    def create_csr(self, common_name: str, key_size: int = _RSA_KEYSIZE,
                   ca: bool = False) -> CSR:
        '''
        Creates an RSA private key and a CSR. After calling this function,
        you can call Secret.get_csr_signature(issuing_ca) afterwards to
        generate the signed certificate

        :param str common_name: common_name for the certificate
        :param int key_size: length of the key in bits
        :param bool ca: create a secret for an CA
        :returns: the Certificate Signature Request
        :raises: ValueError if the Secret instance already has a private key
                 or set
        '''

        if self.private_key or self.cert:
            raise ValueError('Secret already has a cert or private key')

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
            self.get_cert_name()
        ).add_extension(
            x509.BasicConstraints(
                ca=ca, path_length=None
            ), critical=True,
        ).sign(self.private_key, hashes.SHA256())

        return csr

    def csr_as_pem(self, csr):
        '''
        Returns the BASE64 encoded byte string for the CSR

        :returns: bytes with the PEM-encoded certificate
        :raises: (none)
        '''
        return csr.public_bytes(serialization.Encoding.PEM)

    def get_csr_signature(self, csr: CSR, issuing_ca, expire: int = 365):
        '''
        Signs a previously created Certificate Signature Request (CSR)
        with the specified issuing CA

        :param csr: the certificate signature request
        :param Secret issuing_ca: Certificate to sign the CSR with
        :returns: (none)
        :raises: (none)
        '''

        _LOGGER.debug(
            f'Getting CSR with common name {self.common_name} signed'
        )
        self.add_signed_cert(issuing_ca.sign_csr(csr, expire=expire))

    def review_csr(self, csr: CSR) -> str:
        '''
        Check whether the CSR meets our requirements

        :param csr: the certificate signing request to be reviewed
        :returns: commonname of the certificate
        :raises: ValueError if review fails
        '''

        _LOGGER.debug('Reviewing cert sign request')

        if not self.ca:
            _LOGGER.warning('Only CAs review CSRs')
            raise ValueError('Only CAs review CSRs')

        if not csr.is_signature_valid:
            _LOGGER.warning('CSR with invalid signature')
            raise ValueError('CSR with invalid signature')

        sign_algo = csr.signature_algorithm_oid._name
        if sign_algo not in VALID_SIGNATURE_ALGORITHMS:
            _LOGGER.warning(f'CSR with invalid algorithm: {sign_algo}')
            raise ValueError(f'Invalid algorithm: {sign_algo}')

        hash_algo = csr.signature_hash_algorithm.name
        if hash_algo not in VALID_SIGNATURE_HASHES:
            _LOGGER.warning(f'CSR with invalid hash algorithm: {hash_algo}')
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

    def review_commonname(self, commonname: str) -> str:
        '''
        Checks if the structure of common name matches with a common name of
        an AccountSecret. If so, it sets the 'account_id' property of the
        instance to the UUID parsed from the commonname

        :param commonname: the commonname to check
        :returns: commonname with the network domain stripped off, ie. for
        'uuid.accounts.byoda.net' it will return 'uuid.accounts'.
        :raises: ValueError if the commonname is not a string
        '''

        if not isinstance(commonname, str):
            raise ValueError(
                f'Commonname must be of type str, not {type(commonname)}'
            )

        postfix = '.' + self.network
        if not commonname.endswith(postfix):
            raise ValueError(
                f'Commonname {commonname} is not for network {self.network}'
            )

        return commonname[:-1 * len(postfix)]

    def sign_csr(self, csr: CSR, expire: int = 365) -> CertChain:
        '''
        Sign a csr with our private key

        :param - csr: X509.CertificateSigningRequest
        :param int expire: after how many days the cert should
        :returns: the signed cert and the certchain excluding the root CA
        :raises: (none)
        '''

        if not self.ca:
            _LOGGER.warning('Only CAs sign CSRs')
            raise ValueError('Only CAs sign CSRs')

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

    def get_cert_name(self):
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

    def add_signed_cert(self, cert_chain: CertChain):
        '''
        Adds the CA-signed cert and the certchain for the issuing CA
        to the certificate

        :param CertChain cert_chain: cert and its chain of issuing CAs
        :returns: (none)
        :raises: (none)
        '''

        self.cert = cert_chain.signed_cert
        self.cert_chain = cert_chain.cert_chain

    def validate(self, root_ca):
        '''
        Validate that the cert and its certchain are achored to the root cert.
        This function does not check certificate recovation or OCSP

        :param Secret root_ca: the self-signed root CA to validate against
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
        except ValidationError as exc:
            _LOGGER.warning(f'Certchain failed validation: {exc}')
            raise ValueError(f'Certchain failed validation: {exc}')

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

        if self.cert or self.private_key:
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

        # We start parsing the Subject of the CSR, which
        # consists of a list of 'Relative' Distinguished Names
        distinguished_name = ','.join(
            [rdns.rfc4514_string() for rdns in self.cert.subject.rdns]
        )
        self.common_name = self.review_distinguishedname(distinguished_name)

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
        certchain then the certchain can either be included at the beginning
        of the cert_data or can be provided as a separate parameter

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

    def csr_from_string(self, csr: str) -> x509.CertificateSigningRequest:
        '''
        Converts a string to a X.509 CSR

        :param csr: the base64-encoded CSR
        :returns: an X509-encoded CSR
        :raises: (none)
        '''

        if isinstance(csr, str):
            csr = str.encode(csr)

        return x509.load_pem_x509_csr(csr)

    def save(self, password: str = 'byoda'):
        '''
        Save a cert and private key to their respective files

        :param password: password to decrypt the private_key
        :returns: (none)
        :raises: (none)
        '''

        if self.storage_driver.exists(self.cert_file):
            raise ValueError(
                f'Can not save cert because the certificate '
                f'already exists at {self.cert_file}'
            )
        if self.storage_driver.exists(self.private_key_file):
            raise ValueError(
                f'Can not save the private key because the key already '
                f'exists at {self.private_key_file}'
            )

        _LOGGER.debug('Saving cert to %s', self.cert_file)
        data = self.certchain_as_pem()

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

    def certchain_as_pem(self) -> bytes:
        '''
        :returns: the certchain as a bytes array
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

        return data

    def save_tmp_private_key(self) -> str:
        '''
        Create an unencrypted copy of the key to the /tmp directory
        so both the requests library and nginx can read it

        :returns: filename to which the key was saved
        :raises: (none)
        '''

        # TODO: check if file can be deleted after cert/key are added
        # to the requests.Session()
        filepath = '/tmp/private.key'
        _LOGGER.debug('Saving private key to %s', filepath)
        private_key_pem = self.private_key_as_pem()
        with open(filepath, 'wb') as file_desc:
            file_desc.write(private_key_pem)

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

    def encrypt(self, data: bytes):
        '''
        Encrypts the provided data with the Fernet algorithm

        :param bytes data : data to be encrypted
        :returns: encrypted data
        :raises: KeyError if no shared secret was generated or
                            loaded for this instance of Secret
        '''
        if not self.shared_key:
            raise KeyError('No shared secret available to encrypt')

        if isinstance(data, str):
            data = str.encode(data)

        _LOGGER.debug('Encrypting data with %d bytes', len(data))
        ciphertext = self.fernet.encrypt(data)
        return ciphertext

    def decrypt(self, ciphertext: bytes) -> bytes:
        '''
        Decrypts the ciphertext

        :param ciphertext : data to be encrypted
        :returns: encrypted data
        :raises: KeyError if no shared secret was generated
                                  or loaded for this instance of Secret
        '''

        if not self.shared_key:
            raise KeyError('No shared secret available to decrypt')

        data = self.fernet.decrypt(ciphertext)
        _LOGGER.debug('Decrypted data with %d bytes', len(data))

        return data

    def create_shared_key(self, target_secret):
        '''
        Creates an encrypted shared key

        :param Secret target_secret : the target X.509 cert that should be
                                      able to decrypt the shared key
        :returns: (none)
        :raises: (none)
        '''

        _LOGGER.debug(
            f'Creating a shared key protected with cert '
            f'{target_secret.common_name}'
        )

        if self.shared_key:
            _LOGGER.debug('Replacing existing shared key')

        self.shared_key = Fernet.generate_key()

        public_key = target_secret.cert.public_key()
        self.protected_shared_key = public_key.encrypt(
            self.shared_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        _LOGGER.debug('Initializing new Fernet instance')
        self.fernet = Fernet(self.shared_key)

    def load_shared_key(self, protected_shared_key: bytes):
        '''
        Loads a protected shared key

        :param protected_shared_key : the protected shared key
        :returns: (none)
        :raises: (none)
        '''

        _LOGGER.debug(
            f'Decrypting protected shared key with cert {self.common_name}'
        )

        self.protected_shared_key = protected_shared_key
        self.shared_key = self.private_key.decrypt(
            self.protected_shared_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        _LOGGER.debug(
            'Initializing new Fernet instance from decrypted shared secret'
        )
        self.fernet = Fernet(self.shared_key)
