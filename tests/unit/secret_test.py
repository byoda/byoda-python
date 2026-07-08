#!/usr/bin/env python3

'''
Test cases for secrets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import os
import sys
import ssl
import shutil
import asyncio
import secrets
import filecmp
import tempfile
import unittest

from uuid import UUID
from types import SimpleNamespace
from logging import Logger
from random import randint
from typing import Literal
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from httpx2 import Response as HttpResponse
from httpx2 import RequestError

from cryptography import x509
from cryptography.fernet import InvalidToken
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.account import Account
from byoda.datamodel.claim import Claim

from byoda.secrets.networkrootca_secret import NetworkRootCaSecret
from byoda.secrets.network_data_secret import NetworkDataSecret
from byoda.secrets.networkaccountsca_secret import NetworkAccountsCaSecret
from byoda.secrets.networkservicesca_secret import NetworkServicesCaSecret
from byoda.secrets.serviceca_secret import ServiceCaSecret
from byoda.secrets.membersca_secret import MembersCaSecret
from byoda.secrets.appsca_secret import AppsCaSecret
from byoda.servers.pod_server import PodServer

from byoda.secrets.secret import Secret
from byoda.secrets.ca_secret import CaSecret
from byoda.secrets.secret import CertChain
from byoda.secrets.data_secret import DataSecret
from byoda.secrets.app_secret import AppSecret
from byoda.secrets.app_data_secret import AppDataSecret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.datastore.data_store import DataStoreType
from byoda.datastore.cache_store import CacheStoreType

from byoda.datatypes import CloudType
from byoda.datatypes import IdType
from byoda.datatypes import ServerRole

from byoda.datastore.document_store import DocumentStoreType

from byoda.storage.filestorage import FileStorage

from byoda import config

from byoda.util.paths import Paths
from byoda.util.logger import Logger as ByodaLogger

from tests.lib.util import get_test_uuid
from tests.lib.setup import mock_environment_vars
from tests.lib.defines import ADDRESSBOOK_SERVICE_ID


TEST_DIR = '/tmp/byoda-tests/secrets'
NETWORK = 'test.net'
DEFAULT_SCHEMA = 'tests/collateral/dummy-unsigned-service-schema.json'
SERVICE_ID = 12345678
SCHEMA_VERSION = 1
SCHEMA_DIR: str = f'/network-{NETWORK}/services/service-{SERVICE_ID}'
SCHEMA_FILE: str = SCHEMA_DIR + '/service-contract.json'
RSA_KEY_SIZE = 4096


def _selfsigned_secret(common_name: str) -> Secret:
    secret = Secret()
    secret.private_key = secret.generate_private_key()
    secret.common_name = common_name
    secret.create_selfsigned_cert()
    return secret


def _selfsigned_data_secret(common_name: str = 'data.test.net') -> DataSecret:
    secret = DataSecret()
    secret.private_key = secret.generate_private_key()
    secret.common_name = common_name
    secret.create_selfsigned_cert()
    return secret


def _paths(root_dir: str = TEST_DIR, account: str = 'pod') -> Paths:
    storage = FileStorage(root_dir, CloudType.LOCAL)
    return Paths(
        network=NETWORK, root_directory=root_dir, account=account,
        storage_driver=storage,
    )


def _network(
    root_dir: str = TEST_DIR, account: str = 'pod'
) -> SimpleNamespace:
    return SimpleNamespace(name=NETWORK, paths=_paths(root_dir, account))


class _ReviewableCaSecret(CaSecret):
    __slots__ = ['network', 'service_id']

    def __init__(
        self, accepted_csrs: dict[IdType, int] | None = None,
        network: str = NETWORK, service_id: int | None = None,
        is_root_cert: bool = True,
    ) -> None:
        super().__init__('ca.pem', 'ca.key')
        self.network = network
        self.service_id = service_id
        self.accepted_csrs = accepted_csrs or {IdType.ACCOUNT: 30}
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=RSA_KEY_SIZE,
        )
        self.common_name = f'ca.{network}'
        self.create_selfsigned_cert(ca=True)
        self.is_root_cert = is_root_cert

    def review_commonname(self, commonname: str) -> str:
        return CaSecret.review_commonname_by_parameters(
            commonname,
            self.network,
            self.accepted_csrs,
            service_id=self.service_id,
            check_service_id=self.service_id is not None,
        )


def _csr(
    common_name: str,
    sans: list[str] | None = None,
    key_usage: bool = True,
    extended_key_usage: bool = True,
    basic_constraints: x509.BasicConstraints | None = None,
    hash_algorithm=hashes.SHA256(),
) -> x509.CertificateSigningRequest:
    key = rsa.generate_private_key(
        public_exponent=65537, key_size=RSA_KEY_SIZE,
    )
    csr_builder = x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u'SW'),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u'SW'),
            x509.NameAttribute(NameOID.LOCALITY_NAME, u'local'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u'memyselfandi'),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ])
    )

    if sans is not None:
        csr_builder = csr_builder.add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(san) for san in sans]
            ),
            critical=True,
        )

    if key_usage:
        csr_builder = csr_builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )

    if extended_key_usage:
        csr_builder = csr_builder.add_extension(
            x509.ExtendedKeyUsage([
                x509.ExtendedKeyUsageOID.SERVER_AUTH,
                x509.ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )

    if basic_constraints:
        csr_builder = csr_builder.add_extension(
            basic_constraints, critical=True
        )

    return csr_builder.sign(key, hash_algorithm)


def _email_san_csr(common_name: str) -> x509.CertificateSigningRequest:
    key = rsa.generate_private_key(
        public_exponent=65537, key_size=RSA_KEY_SIZE,
    )
    return x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    ).add_extension(
        x509.SubjectAlternativeName([
            x509.RFC822Name('test@example.com')
        ]),
        critical=True,
    ).sign(key, hashes.SHA256())


class _TrackingSecret(Secret):
    __slots__ = ['python_validation_called', 'openssl_validation_called']

    def __init__(self) -> None:
        super().__init__()
        self.python_validation_called = False
        self.openssl_validation_called = False

    def validate_python_cryptography(self, root_ca: Secret) -> None:
        self.python_validation_called = True

    def validate_with_openssl(self, root_ca: Secret) -> None:
        self.openssl_validation_called = True


class _FakeIssuingCa:
    def __init__(self) -> None:
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=RSA_KEY_SIZE,
        )
        self.common_name = 'fake-ca.test.net'
        self.cert = self._create_ca_cert()
        self.csr: x509.CertificateSigningRequest | None = None

    def _create_ca_cert(self) -> x509.Certificate:
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u'SW'),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u'SW'),
            x509.NameAttribute(NameOID.LOCALITY_NAME, u'local'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u'memyselfandi'),
            x509.NameAttribute(NameOID.COMMON_NAME, self.common_name),
        ])
        return x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            self.private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.now(tz=UTC)
        ).not_valid_after(
            datetime.now(tz=UTC) + timedelta(days=1)
        ).add_extension(
            x509.BasicConstraints(ca=True, path_length=1), critical=True,
        ).sign(self.private_key, hashes.SHA256())

    def sign_csr(self, csr: x509.CertificateSigningRequest) -> CertChain:
        self.csr = csr
        cert_builder = x509.CertificateBuilder().subject_name(
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
            datetime.now(tz=UTC) + timedelta(days=1)
        )
        for extension in csr.extensions:
            cert_builder = cert_builder.add_extension(
                extension.value, extension.critical
            )
        cert = cert_builder.sign(self.private_key, hashes.SHA256())
        return CertChain(cert, [self.cert])


class _FakeAsyncHttpClient:
    responses: dict[str, HttpResponse] = {}
    requested_urls: list[str] = []
    verify_values: list[str | None] = []
    request_error: Exception | None = None

    def __init__(self, verify: str | None = None) -> None:
        self.verify_values.append(verify)

    async def __aenter__(self) -> '_FakeAsyncHttpClient':
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url: str) -> HttpResponse:
        if self.request_error:
            raise self.request_error
        self.requested_urls.append(url)
        return self.responses[url]


class TestSecretBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _FakeAsyncHttpClient.request_error = None

    async def test_create_with_issuing_ca_uses_common_name(self) -> None:
        secret = Secret()
        issuing_ca = _FakeIssuingCa()

        await secret.create('leaf.test.net', issuing_ca=issuing_ca)

        self.assertIsInstance(secret.cert, x509.Certificate)
        self.assertEqual(len(secret.cert_chain), 1)
        self.assertEqual(
            Secret.extract_commonname(secret.cert), 'leaf.test.net'
        )

        common_name = None
        for attrib in issuing_ca.csr.subject:
            if attrib.oid == NameOID.COMMON_NAME:
                common_name = attrib.value
                break
        self.assertEqual(common_name, 'leaf.test.net')

    async def test_create_rejects_non_root_self_signed_secret(self) -> None:
        with self.assertRaises(ValueError):
            await Secret().create('leaf.test.net')

    async def test_create_rejects_existing_material(self) -> None:
        secret = Secret()
        secret.private_key = secret.generate_private_key()

        with self.assertRaises(ValueError):
            await secret.create('leaf.test.net')

    async def test_create_csr_rejects_invalid_sans_type(self) -> None:
        with self.assertRaises(ValueError):
            await Secret().create_csr('leaf.test.net', sans=object())

    async def test_create_csr_renew_reuses_existing_private_key(self) -> None:
        secret = Secret()
        original_key = secret.generate_private_key()
        secret.private_key = original_key

        csr = await secret.create_csr('leaf.test.net', renew=True)

        self.assertIs(secret.private_key, original_key)
        self.assertIsInstance(csr, x509.CertificateSigningRequest)

    def test_create_selfsigned_cert_rejects_invalid_expire_type(self) -> None:
        secret = Secret()
        secret.private_key = secret.generate_private_key()
        secret.common_name = 'root.test.net'

        with self.assertRaises(ValueError):
            secret.create_selfsigned_cert(expire='tomorrow')

    def test_create_selfsigned_cert_accepts_datetime_and_timedelta(
        self
    ) -> None:
        secret = Secret()
        secret.private_key = secret.generate_private_key()
        secret.common_name = 'root.test.net'
        expires_at = datetime.now(tz=UTC) + timedelta(days=3)

        secret.create_selfsigned_cert(expire=expires_at)

        self.assertEqual(
            secret.cert.not_valid_after_utc,
            expires_at.replace(microsecond=0),
        )

        other = Secret()
        other.private_key = other.generate_private_key()
        other.common_name = 'other-root.test.net'
        other.create_selfsigned_cert(expire=timedelta(days=1))
        self.assertIsNotNone(other.cert)

    def test_validate_without_openssl_only_uses_python_validator(self) -> None:
        secret = _TrackingSecret()

        secret.validate(Secret(), with_openssl=False)

        self.assertTrue(secret.python_validation_called)
        self.assertFalse(secret.openssl_validation_called)

    def test_from_string_accepts_bytes_certchain_argument(self) -> None:
        leaf = _selfsigned_secret('leaf.test.net')
        issuer = _selfsigned_secret('issuer.test.net')
        secret = Secret()

        secret.from_string(leaf.cert_as_pem(), certchain=issuer.cert_as_pem())

        self.assertEqual(
            Secret.extract_commonname(secret.cert), 'leaf.test.net'
        )
        self.assertEqual(len(secret.cert_chain), 1)
        self.assertEqual(
            Secret.extract_commonname(secret.cert_chain[0]), 'issuer.test.net'
        )

    def test_from_string_rejects_missing_certificate(self) -> None:
        with self.assertRaises(ValueError):
            Secret().from_string('not a certificate')

    async def test_csr_pem_round_trips(self) -> None:
        csr = await Secret().create_csr('leaf.test.net')
        pem = Secret().csr_as_pem(csr)

        parsed = Secret.csr_from_string(pem)

        self.assertEqual(Secret.extract_commonname(parsed), 'leaf.test.net')

    async def test_load_rejects_existing_cert_and_missing_cert_file(
        self
    ) -> None:
        storage = FileStorage(TEST_DIR, CloudType.LOCAL)
        secret = Secret('missing-cert.pem', 'missing-key.pem', storage)

        with self.assertRaises(FileNotFoundError):
            await secret.load(with_private_key=False)

        secret.cert = _selfsigned_secret('leaf.test.net').cert
        with self.assertRaises(ValueError):
            await secret.load(with_private_key=False)

    async def test_load_private_key_error_paths(self) -> None:
        with self.assertRaises(ValueError):
            await Secret('cert.pem', 'key.pem').load_private_key()

        secret = Secret(
            'cert.pem', None, FileStorage(TEST_DIR, CloudType.LOCAL)
        )
        with self.assertRaises(ValueError):
            await secret.load_private_key()

        secret.private_key_file = 'missing-key.pem'
        with self.assertRaises(FileNotFoundError):
            await secret.load_private_key()

    async def test_save_rejects_existing_cert_or_private_key(self) -> None:
        storage = FileStorage(TEST_DIR, CloudType.LOCAL)
        secret = _selfsigned_secret('leaf.test.net')
        secret.cert_file = 'leaf-cert.pem'
        secret.private_key_file = 'leaf-key.pem'
        secret.storage_driver = storage
        await storage.write(secret.cert_file, b'existing-cert')

        with self.assertRaises(PermissionError):
            await secret.save()

        await storage.write(secret.private_key_file, b'existing-key')
        key_secret = _selfsigned_secret('key.test.net')
        key_secret.cert_file = 'new-cert.pem'
        key_secret.private_key_file = secret.private_key_file
        key_secret.storage_driver = storage
        with self.assertRaises(PermissionError):
            await key_secret.save_private_key()

    def test_private_key_and_fingerprint_error_paths(self) -> None:
        secret = Secret()

        with self.assertRaises(ValueError):
            secret.fingerprint()

        with self.assertRaises(AttributeError):
            secret.private_key_as_pem()

        self.assertEqual(
            secret.get_tmp_private_key_filepath('/tmp/test-key.pem'),
            '/tmp/test-key.pem',
        )

    def test_save_tmp_private_key_writes_unencrypted_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            secret = _selfsigned_secret('leaf.test.net')
            filepath = f'{temp_dir}/nested/key.pem'

            self.assertEqual(secret.save_tmp_private_key(filepath), filepath)

            with open(filepath) as file_desc:
                self.assertIn('BEGIN PRIVATE KEY', file_desc.read())

    def test_review_commonname_accepts_valid_member_name(self) -> None:
        member_id = get_test_uuid()

        entity_id = Secret.review_commonname_by_parameters(
            f'{member_id}.mem-{SERVICE_ID}.{NETWORK}',
            NETWORK,
            service_id=SERVICE_ID,
        )

        self.assertEqual(entity_id.id_type, IdType.MEMBER)
        self.assertEqual(entity_id.id, member_id)
        self.assertEqual(entity_id.service_id, SERVICE_ID)

    def test_review_commonname_rejects_wrong_network(self) -> None:
        member_id = get_test_uuid()

        with self.assertRaises(PermissionError):
            Secret.review_commonname_by_parameters(
                f'{member_id}.mem-{SERVICE_ID}.other.net',
                NETWORK,
                service_id=SERVICE_ID,
            )

    def test_review_commonname_rejects_bad_service_id(self) -> None:
        member_id = get_test_uuid()

        with self.assertRaises(PermissionError):
            Secret.review_commonname_by_parameters(
                f'{member_id}.mem-{SERVICE_ID}.{NETWORK}',
                NETWORK,
                service_id=SERVICE_ID + 1,
            )

    def test_review_commonname_rejects_non_uuid_identifier(self) -> None:
        with self.assertRaises(ValueError):
            Secret.review_commonname_by_parameters(
                f'not-a-uuid.mem-{SERVICE_ID}.{NETWORK}',
                NETWORK,
                service_id=SERVICE_ID,
            )

    def test_review_commonname_rejects_malformed_inputs(self) -> None:
        with self.assertRaises(ValueError):
            Secret.review_commonname_by_parameters(
                object(), NETWORK, service_id=SERVICE_ID
            )

        with self.assertRaises(ValueError):
            Secret.review_commonname_by_parameters(
                f'{get_test_uuid()}.unknown-{SERVICE_ID}.{NETWORK}',
                NETWORK, service_id=SERVICE_ID,
            )

        with self.assertRaises(ValueError):
            Secret.review_commonname_by_parameters(
                f'{get_test_uuid()}.mem-x.{NETWORK}',
                NETWORK, service_id=SERVICE_ID,
            )

        with self.assertRaises(ValueError):
            Secret.review_commonname_by_parameters(
                f'{get_test_uuid()}.mem-{pow(2, 32)}.{NETWORK}',
                NETWORK, service_id=pow(2, 32),
            )

        with self.assertRaises(ValueError):
            Secret.review_commonname_by_parameters(
                f'{get_test_uuid()}.mem-{SERVICE_ID}.extra.{NETWORK}',
                NETWORK, service_id=SERVICE_ID,
            )

    async def test_download_returns_fingerprint_fallback_response(
        self
    ) -> None:
        url = 'https://account.test.net/cert.pem'
        _FakeAsyncHttpClient.responses = {
            url: HttpResponse(404, content=b''),
            f'{url}-abc123': HttpResponse(200, content=b'cert-data'),
        }
        _FakeAsyncHttpClient.requested_urls = []
        _FakeAsyncHttpClient.verify_values = []

        original_client = Secret.download.__globals__['AsyncHttpClient']
        Secret.download.__globals__['AsyncHttpClient'] = _FakeAsyncHttpClient
        try:
            cert_data = await Secret.download(
                url, root_ca_filepath='/ca.pem', network_name='test.net',
                fingerprint='abc123'
            )
        finally:
            Secret.download.__globals__['AsyncHttpClient'] = original_client

        self.assertEqual(cert_data, 'cert-data')
        self.assertEqual(
            _FakeAsyncHttpClient.requested_urls,
            [url, f'{url}-abc123'],
        )
        self.assertEqual(_FakeAsyncHttpClient.verify_values, ['/ca.pem'])

    async def test_download_disables_root_ca_for_directory_hosts(self) -> None:
        url = 'https://dir.test.net/cert.pem'
        _FakeAsyncHttpClient.responses = {
            url: HttpResponse(200, content=b'cert-data'),
        }
        _FakeAsyncHttpClient.requested_urls = []
        _FakeAsyncHttpClient.verify_values = []

        original_client = Secret.download.__globals__['AsyncHttpClient']
        Secret.download.__globals__['AsyncHttpClient'] = _FakeAsyncHttpClient
        try:
            await Secret.download(
                url, root_ca_filepath='/ca.pem', network_name='test.net'
            )
        finally:
            Secret.download.__globals__['AsyncHttpClient'] = original_client

        self.assertEqual(_FakeAsyncHttpClient.verify_values, [None])

    async def test_download_raises_for_failed_fingerprint_fallback(
        self
    ) -> None:
        url = 'https://account.test.net/cert.pem'
        _FakeAsyncHttpClient.responses = {
            url: HttpResponse(404, content=b''),
            f'{url}-abc123': HttpResponse(404, content=b''),
        }
        _FakeAsyncHttpClient.requested_urls = []
        original_client = Secret.download.__globals__['AsyncHttpClient']
        Secret.download.__globals__['AsyncHttpClient'] = _FakeAsyncHttpClient
        try:
            with self.assertRaises(RuntimeError):
                await Secret.download(url, fingerprint='abc123')
        finally:
            Secret.download.__globals__['AsyncHttpClient'] = original_client

        self.assertEqual(
            _FakeAsyncHttpClient.requested_urls, [url, f'{url}-abc123']
        )

    async def test_download_wraps_transport_errors(self) -> None:
        url = 'https://account.test.net/cert.pem'
        _FakeAsyncHttpClient.request_error = RequestError('boom')
        original_client = Secret.download.__globals__['AsyncHttpClient']
        Secret.download.__globals__['AsyncHttpClient'] = _FakeAsyncHttpClient
        try:
            with self.assertRaises(RuntimeError):
                await Secret.download(url)
        finally:
            Secret.download.__globals__['AsyncHttpClient'] = original_client
            _FakeAsyncHttpClient.request_error = None


class TestDataSecretBase(unittest.IsolatedAsyncioTestCase):
    async def test_generates_ec_key_and_data_secret_csr_extensions(
        self
    ) -> None:
        secret = DataSecret()

        csr = await secret.create_csr('data.test.net')

        self.assertIsInstance(secret.private_key, ec.EllipticCurvePrivateKey)
        self.assertIsInstance(secret.private_key.curve, ec.SECP256R1)

        key_usage = csr.extensions.get_extension_for_class(
            x509.KeyUsage
        ).value
        self.assertTrue(key_usage.digital_signature)
        self.assertTrue(key_usage.content_commitment)
        self.assertFalse(key_usage.key_encipherment)
        self.assertTrue(key_usage.key_agreement)
        self.assertFalse(key_usage.key_cert_sign)

        extended_key_usage = csr.extensions.get_extension_for_class(
            x509.ExtendedKeyUsage
        ).value
        self.assertIn(
            x509.ExtendedKeyUsageOID.CODE_SIGNING, extended_key_usage
        )
        self.assertIn(
            x509.ExtendedKeyUsageOID.EMAIL_PROTECTION, extended_key_usage
        )

    def test_encrypt_and_decrypt_reject_missing_shared_key(self) -> None:
        secret = DataSecret()

        with self.assertRaises(KeyError):
            secret.encrypt(b'plaintext')

        with self.assertRaises(KeyError):
            secret.decrypt(b'ciphertext')

    def test_encrypt_accepts_string_input_and_decrypts_to_bytes(self) -> None:
        secret = _selfsigned_data_secret()
        secret.create_shared_key()

        ciphertext = secret.encrypt('plaintext')

        self.assertEqual(secret.decrypt(ciphertext), b'plaintext')

    def test_decrypt_rejects_corrupt_ciphertext(self) -> None:
        secret = _selfsigned_data_secret()
        secret.create_shared_key()

        with self.assertRaises(InvalidToken):
            secret.decrypt(b'not-fernet-data')

    def test_load_shared_key_rejects_key_for_different_secret(self) -> None:
        source = _selfsigned_data_secret('source.test.net')
        target = _selfsigned_data_secret('target.test.net')
        wrong_target = _selfsigned_data_secret('wrong-target.test.net')
        source.create_shared_key(target)

        with self.assertRaises(ValueError):
            wrong_target.load_shared_key(source.protected_shared_key)

    def test_load_shared_key_rejects_unsupported_key_format(self) -> None:
        secret = _selfsigned_data_secret()

        with self.assertRaises(ValueError):
            secret.load_shared_key(b'old-rsa-oaep-ciphertext')

    def test_create_shared_key_uses_ec_envelope_format(self) -> None:
        source = _selfsigned_data_secret('source.test.net')
        target = _selfsigned_data_secret('target.test.net')
        source.create_shared_key(target)

        self.assertTrue(
            source.protected_shared_key.startswith(b'BYODA-DATA-KEY-v1\n')
        )
        self.assertNotIn(source.shared_key, source.protected_shared_key)

    def test_create_shared_key_replaces_existing_key(self) -> None:
        secret = _selfsigned_data_secret()
        secret.create_shared_key()
        original_shared_key = secret.shared_key

        secret.create_shared_key()

        self.assertNotEqual(original_shared_key, secret.shared_key)
        self.assertEqual(secret.decrypt(secret.encrypt(b'data')), b'data')

    def test_file_encryption_round_trips_edge_sizes(self) -> None:
        secret = _selfsigned_data_secret()
        secret.create_shared_key()

        cases = {
            'empty': b'',
            'exact': b'a' * 7,
            'one_over': b'b' * 8,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            for name, data in cases.items():
                source_file = os.path.join(temp_dir, name)
                protected_file = source_file + '.protected'
                out_file = source_file + '.out'
                with open(source_file, 'wb') as file_desc:
                    file_desc.write(data)

                secret.encrypt_file(source_file, protected_file, block_size=7)
                secret.decrypt_file(protected_file, out_file)

                with open(out_file, 'rb') as file_desc:
                    self.assertEqual(file_desc.read(), data)

    def test_decrypt_file_rejects_truncated_encrypted_chunk(self) -> None:
        secret = _selfsigned_data_secret()
        secret.create_shared_key()

        with tempfile.TemporaryDirectory() as temp_dir:
            protected_file = os.path.join(temp_dir, 'data.protected')
            out_file = os.path.join(temp_dir, 'data.out')
            encrypted_chunk = secret.encrypt(b'plaintext')
            with open(protected_file, 'wb') as file_desc:
                file_desc.write(len(encrypted_chunk).to_bytes(4, 'little'))
                file_desc.write(encrypted_chunk[:-1])

            with self.assertRaises(ValueError):
                secret.decrypt_file(protected_file, out_file)

    def test_decrypt_file_rejects_corrupted_encrypted_chunk(self) -> None:
        secret = _selfsigned_data_secret()
        secret.create_shared_key()

        with tempfile.TemporaryDirectory() as temp_dir:
            protected_file = os.path.join(temp_dir, 'data.protected')
            out_file = os.path.join(temp_dir, 'data.out')
            encrypted_chunk = bytearray(secret.encrypt(b'plaintext'))
            encrypted_chunk[-2] ^= 1
            with open(protected_file, 'wb') as file_desc:
                file_desc.write(len(encrypted_chunk).to_bytes(4, 'little'))
                file_desc.write(encrypted_chunk)

            with self.assertRaises(InvalidToken):
                secret.decrypt_file(protected_file, out_file)

    def test_decrypt_file_rejects_truncated_length_prefix(self) -> None:
        secret = _selfsigned_data_secret()
        secret.create_shared_key()

        with tempfile.TemporaryDirectory() as temp_dir:
            protected_file = os.path.join(temp_dir, 'data.protected')
            out_file = os.path.join(temp_dir, 'data.out')
            with open(protected_file, 'wb') as file_desc:
                file_desc.write(b'\x10\x00')

            with self.assertRaises(ValueError):
                secret.decrypt_file(protected_file, out_file)

    def test_sign_and_verify_reject_invalid_inputs(self) -> None:
        secret = _selfsigned_data_secret()

        with self.assertRaises(ValueError):
            secret.sign_message(object())

        with self.assertRaises(ValueError):
            secret.verify_message_signature(object(), b'signature')

    def test_sign_rejects_unsupported_hash_algorithm(self) -> None:
        secret = _selfsigned_data_secret()

        with self.assertRaises(ValueError):
            secret.sign_message('message', hash_algorithm='SHA512')

        signature = secret.sign_message('message')
        with self.assertRaises(NotImplementedError):
            secret.verify_message_signature(
                'message', signature, hash_algorithm='SHA512'
            )

    def test_verify_rejects_altered_message_signature_and_wrong_cert(
        self
    ) -> None:
        secret = _selfsigned_data_secret('signer.test.net')
        wrong_secret = _selfsigned_data_secret('wrong.test.net')
        signature = secret.sign_message(b'message')

        with self.assertRaises(InvalidSignature):
            secret.verify_message_signature(b'tampered', signature)

        bad_signature = bytearray(signature)
        bad_signature[-1] ^= 1
        with self.assertRaises(InvalidSignature):
            secret.verify_message_signature(b'message', bytes(bad_signature))

        with self.assertRaises(InvalidSignature):
            wrong_secret.verify_message_signature(b'message', signature)

    async def test_download_uses_default_ca_path_and_forwards_arguments(
        self
    ) -> None:
        calls = []

        async def fake_download(
            url, root_ca_filepath=None, network_name=None, fingerprint=None
        ):
            calls.append((url, root_ca_filepath, network_name, fingerprint))
            return 'cert-data'

        class FakePaths:
            storage_driver = SimpleNamespace(local_path='/storage-root')

            def get(self, path_template):
                self.path_template = path_template
                return '/network-test/root-ca.pem'

        data_secret = DataSecret()
        original_download = Secret.download
        original_server = getattr(config, 'server', None)
        paths = FakePaths()
        Secret.download = staticmethod(fake_download)
        config.server = SimpleNamespace(paths=paths)
        try:
            cert_data = await data_secret.download(
                'https://member.test.net/data.pem',
                network_name='test.net',
                fingerprint='abc123',
            )
        finally:
            Secret.download = original_download
            config.server = original_server

        self.assertEqual(cert_data, 'cert-data')
        self.assertEqual(paths.path_template, Paths.NETWORK_ROOT_CA_CERT_FILE)
        self.assertEqual(
            calls,
            [(
                'https://member.test.net/data.pem',
                '/storage-root/network-test/root-ca.pem',
                'test.net',
                'abc123',
            )],
        )

    async def test_download_prefers_explicit_ca_path(self) -> None:
        calls = []

        async def fake_download(
            url, root_ca_filepath=None, network_name=None, fingerprint=None
        ):
            calls.append((url, root_ca_filepath, network_name, fingerprint))
            return 'cert-data'

        original_download = Secret.download
        Secret.download = staticmethod(fake_download)
        try:
            cert_data = await DataSecret().download(
                'https://member.test.net/data.pem',
                ca_filepath='/explicit-ca.pem',
            )
        finally:
            Secret.download = original_download

        self.assertEqual(cert_data, 'cert-data')
        self.assertEqual(
            calls,
            [(
                'https://member.test.net/data.pem',
                '/explicit-ca.pem',
                None,
                None,
            )],
        )


class TestNetworkDataSecretBase(unittest.IsolatedAsyncioTestCase):
    async def test_create_uses_network_data_common_name(self) -> None:
        paths = Paths(
            network=NETWORK,
            root_directory=TEST_DIR,
            storage_driver=FileStorage(TEST_DIR, CloudType.LOCAL),
        )
        secret = NetworkDataSecret(paths)
        secret.is_root_cert = True

        await secret.create()

        self.assertEqual(
            secret.common_name,
            f'network.{IdType.NETWORK_DATA.value}.{NETWORK}',
        )

    async def test_create_csr_uses_network_data_common_name(self) -> None:
        paths = Paths(
            network=NETWORK,
            root_directory=TEST_DIR,
            storage_driver=FileStorage(TEST_DIR, CloudType.LOCAL),
        )
        secret = NetworkDataSecret(paths)

        csr = await secret.create_csr()

        self.assertEqual(
            Secret.extract_commonname(csr),
            f'network.{IdType.NETWORK_DATA.value}.{NETWORK}',
        )


class TestMemberSecretBase(unittest.IsolatedAsyncioTestCase):
    def test_constructor_requires_paths_or_account_and_network(self) -> None:
        with self.assertRaises(ValueError):
            MemberSecret(get_test_uuid(), SERVICE_ID)

        with self.assertRaises(ValueError):
            MemberSecret(get_test_uuid(), SERVICE_ID, paths=_paths())

    def test_create_commonname_contract(self) -> None:
        member_id = get_test_uuid()

        self.assertEqual(
            MemberSecret.create_commonname(member_id, SERVICE_ID, NETWORK),
            f'{member_id}.{IdType.MEMBER.value}{SERVICE_ID}.{NETWORK}',
        )

        with self.assertRaises(ValueError):
            MemberSecret.create_commonname(None, SERVICE_ID, NETWORK)

        with self.assertRaises(TypeError):
            MemberSecret.create_commonname(member_id, SERVICE_ID, object())

    async def test_create_csr_and_tmp_key_path(self) -> None:
        member_id = get_test_uuid()
        secret = MemberSecret(
            member_id, SERVICE_ID, paths=_paths(), network_name=NETWORK
        )

        csr = await secret.create_csr()

        self.assertEqual(
            Secret.extract_commonname(csr),
            MemberSecret.create_commonname(member_id, SERVICE_ID, NETWORK),
        )
        self.assertIn(str(member_id), secret.get_tmp_private_key_filepath())

    async def test_load_sets_member_id_from_certificate_common_name(
        self
    ) -> None:
        member_id = get_test_uuid()
        secret = MemberSecret(
            member_id, SERVICE_ID, paths=_paths(), network_name=NETWORK
        )
        cert = _selfsigned_secret(
            MemberSecret.create_commonname(member_id, SERVICE_ID, NETWORK)
        )
        await secret.storage_driver.write(secret.cert_file, cert.cert_as_pem())
        secret.member_id = None

        await secret.load(with_private_key=False)

        self.assertEqual(secret.member_id, member_id)

    async def test_download_falls_back_to_service_server(self) -> None:
        member_id = get_test_uuid()
        cert = _selfsigned_secret(
            MemberSecret.create_commonname(member_id, SERVICE_ID, NETWORK)
        )
        calls: list[tuple[str, str | None]] = []

        async def fake_download(url, root_ca_filepath=None, **kwargs):
            calls.append((url, root_ca_filepath))
            if len(calls) == 1:
                raise RuntimeError('pod unavailable')
            return cert.cert_as_pem().decode('utf-8')

        original_download = Secret.download
        Secret.download = staticmethod(fake_download)
        try:
            secret = await MemberSecret.download(
                member_id, SERVICE_ID, NETWORK, _paths(), '/root-ca.pem'
            )
        finally:
            Secret.download = original_download

        self.assertEqual(secret.member_id, member_id)
        self.assertEqual(
            calls,
            [
                (
                    Paths.resolve(
                        Paths.MEMBER_CERT_DOWNLOAD, network=NETWORK,
                        service_id=SERVICE_ID, member_id=member_id,
                    ),
                    '/root-ca.pem',
                ),
                (
                    Paths.resolve(
                        Paths.SERVICE_MEMBER_CERT_DOWNLOAD, network=NETWORK,
                        service_id=SERVICE_ID, member_id=member_id,
                    ),
                    '/root-ca.pem',
                ),
            ],
        )


class TestAppSecretBase(unittest.IsolatedAsyncioTestCase):
    async def test_create_csr_adds_fqdn_san(self) -> None:
        app_id = get_test_uuid()
        secret = AppSecret(app_id, SERVICE_ID, _network())

        csr = await secret.create_csr('app.example.test')

        self.assertEqual(
            Secret.extract_commonname(csr),
            AppSecret.create_commonname(app_id, SERVICE_ID, NETWORK),
        )
        sans = csr.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.DNSName)
        self.assertIn('app.example.test', sans)

    def test_create_commonname_and_tmp_key_contract(self) -> None:
        app_id = get_test_uuid()
        secret = AppSecret(app_id, SERVICE_ID, _network())

        self.assertEqual(
            AppSecret.create_commonname(str(app_id), SERVICE_ID, NETWORK),
            f'{app_id}.{IdType.APP.value}{SERVICE_ID}.{NETWORK}',
        )
        self.assertIn(str(app_id), secret.get_tmp_private_key_filepath())

        with self.assertRaises(TypeError):
            AppSecret.create_commonname(app_id, SERVICE_ID, object())

    async def test_load_rejects_mismatched_app_id(self) -> None:
        app_id = get_test_uuid()
        other_app_id = get_test_uuid()
        secret = AppSecret(app_id, SERVICE_ID, _network())
        cert = _selfsigned_secret(
            AppSecret.create_commonname(other_app_id, SERVICE_ID, NETWORK)
        )
        await secret.storage_driver.write(secret.cert_file, cert.cert_as_pem())

        with self.assertRaises(ValueError):
            await secret.load(with_private_key=False)


class TestAppDataSecretBase(unittest.IsolatedAsyncioTestCase):
    async def test_create_csr_adds_fqdn_san(self) -> None:
        app_id = get_test_uuid()
        secret = AppDataSecret(app_id, SERVICE_ID, _network())

        csr = await secret.create_csr('data.example.test')

        self.assertEqual(
            Secret.extract_commonname(csr),
            AppDataSecret.create_commonname(app_id, SERVICE_ID, NETWORK),
        )
        sans = csr.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.DNSName)
        self.assertIn('data.example.test', sans)

    def test_create_commonname_contract(self) -> None:
        app_id = get_test_uuid()

        self.assertEqual(
            AppDataSecret.create_commonname(str(app_id), SERVICE_ID, NETWORK),
            f'{app_id}.{IdType.APP_DATA.value}{SERVICE_ID}.{NETWORK}',
        )

        with self.assertRaises(TypeError):
            AppDataSecret.create_commonname(app_id, SERVICE_ID, object())

    async def test_download_forwards_path_and_fingerprint(self) -> None:
        app_id = get_test_uuid()
        secret = AppDataSecret(app_id, SERVICE_ID, _network())
        calls = []

        async def fake_download(
            self, url, ca_filepath=None, network_name=None, fingerprint=None
        ):
            calls.append((url, ca_filepath, network_name, fingerprint))
            return 'cert-data'

        original_download = DataSecret.download
        DataSecret.download = fake_download
        try:
            cert_data = await secret.download(fingerprint='abc123')
        finally:
            DataSecret.download = original_download

        self.assertEqual(cert_data, 'cert-data')
        self.assertEqual(
            calls[0][0],
            secret.paths.get(Paths.APP_DATACERT_DOWNLOAD, app_id=app_id),
        )
        self.assertEqual(calls[0][3], 'abc123')

    async def test_download_cert_uses_and_populates_cache(self) -> None:
        app_id = get_test_uuid()
        fingerprint = 'abc123'
        cached_cert = _selfsigned_data_secret(
            AppDataSecret.create_commonname(app_id, SERVICE_ID, NETWORK)
        ).cert
        original_data_certs = getattr(config, 'data_certs', None)
        config.data_certs = {
            fingerprint: {IdType.APP_DATA: cached_cert}
        }
        try:
            secret = AppDataSecret(app_id, SERVICE_ID, _network())
            await secret.download_cert(fingerprint=fingerprint)
            self.assertIs(secret.cert, cached_cert)

            downloaded = _selfsigned_data_secret(
                AppDataSecret.create_commonname(app_id, SERVICE_ID, NETWORK)
            )
            config.data_certs = {}

            async def fake_download(
                self, url, ca_filepath=None, network_name=None,
                fingerprint=None
            ):
                return downloaded.cert_as_pem().decode('utf-8')

            original_download = DataSecret.download
            DataSecret.download = fake_download
            try:
                await secret.download_cert(fingerprint=fingerprint)
            finally:
                DataSecret.download = original_download

            self.assertIs(
                config.data_certs[fingerprint][IdType.APP_DATA],
                secret.cert,
            )
        finally:
            if original_data_certs is None:
                delattr(config, 'data_certs')
            else:
                config.data_certs = original_data_certs

    async def test_load_rejects_mismatched_app_id(self) -> None:
        app_id = get_test_uuid()
        other_app_id = get_test_uuid()
        secret = AppDataSecret(app_id, SERVICE_ID, _network())
        cert = _selfsigned_data_secret(
            AppDataSecret.create_commonname(other_app_id, SERVICE_ID, NETWORK)
        )
        await secret.storage_driver.write(secret.cert_file, cert.cert_as_pem())

        with self.assertRaises(ValueError):
            await secret.load(with_private_key=False)


class TestMemberDataSecretBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_server = getattr(config, 'server', None)
        config.server = SimpleNamespace(network=_network())

    def tearDown(self) -> None:
        config.server = self.original_server

    async def test_create_and_create_csr_use_member_data_common_name(
        self
    ) -> None:
        member_id = get_test_uuid()
        secret = MemberDataSecret(member_id, SERVICE_ID)
        secret.is_root_cert = True

        await secret.create()
        self.assertEqual(
            secret.common_name,
            MemberDataSecret.create_common_name(
                member_id, SERVICE_ID, NETWORK
            ),
        )

        csr_secret = MemberDataSecret(member_id, SERVICE_ID)
        csr = await csr_secret.create_csr()
        self.assertEqual(
            Secret.extract_commonname(csr),
            MemberDataSecret.create_common_name(
                member_id, SERVICE_ID, NETWORK
            ),
        )

    def test_create_common_name_accepts_network_object(self) -> None:
        member_id = get_test_uuid()

        self.assertEqual(
            MemberDataSecret.create_common_name(
                member_id, SERVICE_ID, _network()
            ),
            f'{member_id}.{IdType.MEMBER_DATA.value}{SERVICE_ID}.{NETWORK}',
        )

    async def test_download_falls_back_to_service_server(self) -> None:
        member_id = get_test_uuid()
        cert = _selfsigned_data_secret(
            MemberDataSecret.create_common_name(member_id, SERVICE_ID, NETWORK)
        )
        calls: list[tuple[str, str | None]] = []

        async def fake_download(self, url, network_name=None, **kwargs):
            calls.append((url, network_name))
            if len(calls) == 1:
                raise RuntimeError('pod unavailable')
            return cert.cert_as_pem().decode('utf-8')

        original_download = DataSecret.download
        DataSecret.download = fake_download
        try:
            secret = await MemberDataSecret.download(
                member_id, SERVICE_ID, NETWORK
            )
        finally:
            DataSecret.download = original_download

        self.assertEqual(secret.common_name, cert.common_name)
        self.assertEqual(
            calls,
            [
                (
                    Paths.resolve(
                        Paths.MEMBER_DATACERT_DOWNLOAD, network=NETWORK,
                        service_id=SERVICE_ID, member_id=member_id,
                    ),
                    NETWORK,
                ),
                (
                    Paths.resolve(
                        Paths.SERVICE_MEMBER_DATACERT_DOWNLOAD,
                        network=NETWORK, service_id=SERVICE_ID,
                        member_id=member_id,
                    ),
                    None,
                ),
            ],
        )

    def test_from_string_sets_common_name(self) -> None:
        member_id = get_test_uuid()
        cert = _selfsigned_data_secret(
            MemberDataSecret.create_common_name(member_id, SERVICE_ID, NETWORK)
        )
        secret = MemberDataSecret(member_id, SERVICE_ID)

        secret.from_string(cert.cert_as_pem())

        self.assertEqual(secret.common_name, cert.common_name)


class TestCaSecretBase(unittest.IsolatedAsyncioTestCase):
    async def test_review_csr_accepts_valid_csr(self) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        ca = _ReviewableCaSecret()
        csr = await Secret().create_csr(common_name)

        self.assertEqual(ca.review_csr(csr), common_name)

    async def test_review_csr_rejects_missing_key_file_and_non_ca(
        self
    ) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        csr = await Secret().create_csr(common_name)
        ca = _ReviewableCaSecret()

        ca.private_key_file = None
        with self.assertRaises(ValueError):
            ca.review_csr(csr)

        ca.private_key_file = 'ca.key'
        ca.ca = False
        with self.assertRaises(ValueError):
            ca.review_csr(csr)

    def test_review_csr_rejects_invalid_signature(self) -> None:
        ca = _ReviewableCaSecret()
        csr = SimpleNamespace(is_signature_valid=False)

        with self.assertRaises(ValueError):
            ca.review_csr(csr)

    def test_review_csr_rejects_unsupported_signature_algorithm(self) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        ca = _ReviewableCaSecret()
        csr = _csr(common_name, [common_name], hash_algorithm=hashes.SHA512())

        with self.assertRaises(ValueError):
            ca.review_csr(csr)

    def test_review_csr_rejects_common_name_subject_alt_name_mismatch(
        self
    ) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        ca = _ReviewableCaSecret()
        csr = _csr(common_name, [f'{get_test_uuid()}.accounts.{NETWORK}'])

        with self.assertRaises(ValueError):
            ca.review_csr(csr)

    def test_review_subjectalternative_name_contract(self) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        ca = _ReviewableCaSecret()

        self.assertEqual(
            ca.review_subjectalternative_name(
                _csr(common_name, [common_name, 'alias.test.net']),
                max_dns_names=2,
            ),
            common_name,
        )

        with self.assertRaises(ValueError):
            ca.review_subjectalternative_name(
                _csr(common_name, [common_name, 'alias.test.net'])
            )

        with self.assertRaises(ValueError):
            ca.review_subjectalternative_name(_csr(common_name, None))

        with self.assertRaises(ValueError):
            ca.review_subjectalternative_name(_email_san_csr(common_name))

    def test_review_distinguishedname_contract(self) -> None:
        ca = _ReviewableCaSecret()

        self.assertEqual(
            ca.review_distinguishedname(
                'C=SW,ST=SW,L=local,O=memyselfandi,CN=leaf.test.net'
            ),
            'leaf.test.net',
        )

        for name in ['CN=', 'OU=unknown,CN=leaf.test.net', 'C=SW,O=org']:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    ca.review_distinguishedname(name)

        with self.assertRaises(ValueError):
            ca.review_distinguishedname('malformed')

    def test_review_commonname_by_parameters_enforces_accepted_csrs(
        self
    ) -> None:
        account_id = get_test_uuid()

        entity_id = CaSecret.review_commonname_by_parameters(
            f'{account_id}.accounts.{NETWORK}',
            NETWORK,
            {IdType.ACCOUNT: 30},
            check_service_id=False,
        )

        self.assertEqual(entity_id.id_type, IdType.ACCOUNT)
        self.assertEqual(entity_id.id, account_id)

        with self.assertRaises(PermissionError):
            CaSecret.review_commonname_by_parameters(
                f'{account_id}.accounts.{NETWORK}',
                NETWORK,
                {IdType.MEMBER: 30},
                check_service_id=False,
            )

    def test_review_commonname_coerces_service_id(self) -> None:
        member_id = get_test_uuid()

        entity_id = CaSecret.review_commonname_by_parameters(
            f'{member_id}.mem-{SERVICE_ID}.{NETWORK}',
            NETWORK,
            {IdType.MEMBER: 30},
            service_id=str(SERVICE_ID),
        )

        self.assertEqual(entity_id.id_type, IdType.MEMBER)
        self.assertEqual(entity_id.service_id, SERVICE_ID)

    async def test_sign_csr_default_expire_reviews_and_uses_allowlist(
        self
    ) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        ca = _ReviewableCaSecret({IdType.ACCOUNT: 30})
        csr = await Secret().create_csr(common_name)

        cert_chain = ca.sign_csr(csr)

        self.assertEqual(Secret.extract_commonname(cert_chain.signed_cert),
                         common_name)
        self.assertEqual(len(cert_chain.cert_chain), 0)
        lifetime = (
            cert_chain.signed_cert.not_valid_after_utc -
            cert_chain.signed_cert.not_valid_before_utc
        )
        self.assertGreaterEqual(lifetime.days, 29)
        self.assertLessEqual(lifetime.days, 30)

    async def test_sign_csr_rejects_unaccepted_entity_without_expire(
        self
    ) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        ca = _ReviewableCaSecret({IdType.MEMBER: 30})
        csr = await Secret().create_csr(common_name)

        with self.assertRaises(PermissionError):
            ca.sign_csr(csr)

    async def test_sign_csr_error_paths(self) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        ca = _ReviewableCaSecret()
        csr = await Secret().create_csr(common_name)

        ca.ca = False
        with self.assertRaises(ValueError):
            ca.sign_csr(csr, expire=1)

        ca.ca = True
        ca.private_key = None
        with self.assertRaises(KeyError):
            ca.sign_csr(csr, expire=1)

        ca.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=RSA_KEY_SIZE,
        )
        with self.assertRaises(ValueError):
            ca.sign_csr(csr, expire='tomorrow')

        with self.assertRaises(ValueError):
            ca.sign_csr(_csr(common_name, [common_name], key_usage=False),
                        expire=1)

    def test_sign_csr_preserves_requested_certificate_extensions(self) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        ca = _ReviewableCaSecret(is_root_cert=False)
        issuer_cert = ca.cert
        csr = _csr(
            common_name,
            [common_name],
            basic_constraints=x509.BasicConstraints(ca=True, path_length=0),
        )

        cert_chain = ca.sign_csr(csr, expire=timedelta(days=3))
        cert = cert_chain.signed_cert

        key_usage = cert.extensions.get_extension_for_class(x509.KeyUsage)
        self.assertTrue(key_usage.value.digital_signature)
        self.assertTrue(key_usage.value.key_encipherment)

        extended_key_usage = cert.extensions.get_extension_for_class(
            x509.ExtendedKeyUsage
        )
        self.assertIn(
            x509.ExtendedKeyUsageOID.SERVER_AUTH, extended_key_usage.value
        )

        basic_constraints = cert.extensions.get_extension_for_class(
            x509.BasicConstraints
        )
        self.assertTrue(basic_constraints.value.ca)
        self.assertEqual(basic_constraints.value.path_length, None)

        cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
        self.assertEqual(len(cert_chain.cert_chain), 1)
        self.assertEqual(cert_chain.cert_chain[0], issuer_cert)

    async def test_sign_csr_expire_accepts_int_datetime_and_timedelta(
        self
    ) -> None:
        common_name = f'{get_test_uuid()}.accounts.{NETWORK}'
        ca = _ReviewableCaSecret()
        csr = await Secret().create_csr(common_name)

        ca.sign_csr(csr, expire=1)
        ca.sign_csr(csr, expire=timedelta(days=1))
        expires_at = datetime.now(tz=UTC) + timedelta(days=1)
        cert_chain = ca.sign_csr(csr, expire=expires_at)

        self.assertEqual(
            cert_chain.signed_cert.not_valid_after_utc,
            expires_at.replace(microsecond=0),
        )


class TestCaSecretSubclasses(unittest.IsolatedAsyncioTestCase):
    def test_network_accounts_ca_commonname_policy(self) -> None:
        account_id = get_test_uuid()
        entity_id = NetworkAccountsCaSecret.review_commonname_by_parameters(
            f'{account_id}.{IdType.ACCOUNT_DATA.value}.{NETWORK}',
            NETWORK,
        )

        self.assertEqual(entity_id.id_type, IdType.ACCOUNT_DATA)
        self.assertEqual(entity_id.id, account_id)

        with self.assertRaises(PermissionError):
            NetworkAccountsCaSecret.review_commonname_by_parameters(
                f'{account_id}.{IdType.MEMBER.value}{SERVICE_ID}.{NETWORK}',
                NETWORK,
            )

    def test_network_services_ca_commonname_policy(self) -> None:
        entity_id = NetworkServicesCaSecret.review_commonname_by_parameters(
            f'{IdType.SERVICE_CA.value.rstrip("-")}.'
            f'{IdType.SERVICE_CA.value}{SERVICE_ID}.{NETWORK}',
            NETWORK,
        )

        self.assertEqual(entity_id.id_type, IdType.SERVICE_CA)
        self.assertEqual(entity_id.service_id, SERVICE_ID)

    def test_network_root_ca_policy_and_source_rejection(self) -> None:
        entity_id = NetworkRootCaSecret.review_commonname_by_parameters(
            f'network.{IdType.NETWORK_DATA.value}.{NETWORK}',
            NETWORK,
        )
        self.assertEqual(entity_id.id_type, IdType.NETWORK_DATA)

        root_ca = NetworkRootCaSecret(network=NETWORK)
        root_ca.private_key_file = 'root-ca.key'
        csr = SimpleNamespace()
        with self.assertRaises(ValueError):
            root_ca.review_csr(csr)

        with self.assertRaises(NotImplementedError):
            asyncio.run(root_ca.create_csr())

    async def test_service_ca_source_and_service_id_policy(self) -> None:
        service_ca = ServiceCaSecret(SERVICE_ID, _network())
        csr = await Secret().create_csr(
            f'{IdType.MEMBERS_CA.value.rstrip("-")}.'
            f'{IdType.MEMBERS_CA.value}{SERVICE_ID}.{NETWORK}'
        )

        with self.assertRaises(ValueError):
            service_ca.review_csr(csr)

        with self.assertRaises(ValueError):
            ServiceCaSecret(-1, _network())

    def test_members_ca_commonname_policy(self) -> None:
        member_id = get_test_uuid()
        entity_id = MembersCaSecret.review_commonname_by_parameters(
            f'{member_id}.{IdType.MEMBER_DATA.value}{SERVICE_ID}.{NETWORK}',
            NETWORK,
            SERVICE_ID,
        )

        self.assertEqual(entity_id.id_type, IdType.MEMBER_DATA)
        self.assertEqual(entity_id.id, member_id)

        with self.assertRaises(PermissionError):
            MembersCaSecret.review_commonname_by_parameters(
                f'{member_id}.{IdType.MEMBER.value}{SERVICE_ID + 1}.{NETWORK}',
                NETWORK,
                SERVICE_ID,
            )

    def test_apps_ca_commonname_policy_and_san_contract(self) -> None:
        app_id = get_test_uuid()
        entity_id = AppsCaSecret.review_commonname_by_parameters(
            f'{app_id}.{IdType.APP_DATA.value}{SERVICE_ID}.{NETWORK}',
            NETWORK,
            SERVICE_ID,
        )

        self.assertEqual(entity_id.id_type, IdType.APP_DATA)
        self.assertEqual(entity_id.id, app_id)

        with self.assertRaises(PermissionError):
            AppsCaSecret.review_commonname_by_parameters(
                f'{app_id}.{IdType.APP.value}{SERVICE_ID + 1}.{NETWORK}',
                NETWORK,
                SERVICE_ID,
            )

        ca = AppsCaSecret(SERVICE_ID, _network())
        common_name = f'{app_id}.{IdType.APP.value}{SERVICE_ID}.{NETWORK}'
        with self.assertRaises(ValueError):
            ca.review_subjectalternative_name(
                _csr(common_name, ['other.name'])
            )

        with self.assertRaises(ValueError):
            ca.review_subjectalternative_name(_csr(common_name, [common_name]))


class TestAccountManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        try:
            shutil.rmtree(TEST_DIR)
        except FileNotFoundError:
            pass

        mock_environment_vars(TEST_DIR)
        os.makedirs(TEST_DIR + SCHEMA_DIR)
        shutil.copy(DEFAULT_SCHEMA, TEST_DIR + SCHEMA_FILE)
        config.test_case = True

    async def asyncTearDown(self) -> None:
        '''
        Nothing to tear down
        '''

        server: PodServer = config.server
        await server.shutdown()

    async def test_ca_pathlen(self) -> None:
        storage = FileStorage(TEST_DIR, CloudType.LOCAL)
        root_ca: CaSecret = CaSecret(
            'root-ca.pem', 'root-ca.key', storage
        )
        root_ca.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=RSA_KEY_SIZE,
        )
        root_ca.common_name = 'test-root-ca'
        root_ca.create_selfsigned_cert(ca=True)
        await root_ca.save()

        services_ca: CaSecret = CaSecret(
            'services-ca.pem', 'services-ca.key', storage
        )
        services_ca_csr: x509.CertificateSigningRequest = \
            await services_ca.create_csr('test-services-ca')
        certchain: CertChain = root_ca.sign_csr(services_ca_csr, expire=3)
        services_ca.from_signed_cert(certchain)
        await services_ca.save(with_fingerprint=True)
        services_ca.validate(root_ca, with_openssl=True)

        service_ca: CaSecret = CaSecret(
            'service-ca.pem', 'service-ca.key', storage
        )
        service_ca_csr: x509.CertificateSigningRequest = \
            await service_ca.create_csr('test-service-ca')
        certchain: CertChain = services_ca.sign_csr(service_ca_csr, expire=3)
        service_ca.from_signed_cert(certchain)
        await service_ca.save(with_fingerprint=True)
        service_ca.validate(root_ca, with_openssl=True)

        member_secret: Secret = Secret(
            'member.pem', 'member.key', storage
        )
        member_csr: x509.CertificateSigningRequest = \
            await member_secret.create_csr('test-member')
        certchain: CertChain = service_ca.sign_csr(member_csr, expire=3)
        member_secret.from_signed_cert(certchain)
        await member_secret.save(with_fingerprint=True)
        member_secret.validate(root_ca, with_openssl=True)

    async def test_ca_pathlen_fail(self) -> None:
        storage = FileStorage(TEST_DIR, CloudType.LOCAL)
        root_ca: CaSecret = CaSecret(
            'root-ca.pem', 'root-ca.key', storage
        )
        root_ca.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=RSA_KEY_SIZE,
        )
        root_ca.common_name = 'test-root-ca'
        root_ca.create_selfsigned_cert(ca=True)
        await root_ca.save()

        services_ca: CaSecret = CaSecret(
            'services-ca.pem', 'services-ca.key', storage
        )
        services_ca_csr: x509.CertificateSigningRequest = \
            await services_ca.create_csr(
                'test-services-ca'
            )
        certchain: CertChain = root_ca.sign_csr(services_ca_csr, expire=3)
        services_ca.from_signed_cert(certchain)
        await services_ca.save()
        services_ca.validate(root_ca, with_openssl=True)

        service_ca: CaSecret = CaSecret(
            'service-ca.pem', 'service-ca.key', storage
        )
        service_ca_csr: x509.CertificateSigningRequest = \
            await service_ca.create_csr(
                'test-service-ca'
            )
        service_ca_certchain: CertChain = root_ca.sign_csr(
            service_ca_csr, expire=3
        )
        service_ca.from_signed_cert(service_ca_certchain)
        await service_ca.save()
        service_ca.validate(root_ca, with_openssl=True)

        members_ca: CaSecret = CaSecret(
            'members_ca.pem', 'members-ca.key', storage
        )
        members_ca_csr: x509.CertificateSigningRequest = \
            await members_ca.create_csr(
                'test-members-ca'
            )
        members_ca_certchain: CertChain = service_ca.sign_csr(
            members_ca_csr, expire=3
        )
        members_ca.from_signed_cert(members_ca_certchain)
        await members_ca.save()

        member_secret: Secret = Secret(
            'member.pem', 'member.key', storage
        )
        member_csr: x509.CertificateSigningRequest = \
            await member_secret.create_csr(
                'test-member'
            )
        member_certchain: CertChain = members_ca.sign_csr(
            member_csr, expire=1
        )
        member_secret.from_signed_cert(member_certchain)
        await member_secret.save()

        member_secret.validate(root_ca, with_openssl=True)
        member_secret.validate(root_ca, with_openssl=False)

    async def test_ca_certchain(self) -> None:
        network: Network = await Network.create(NETWORK, TEST_DIR, 'byoda')
        self.assertEqual(
            network.data_secret.common_name,
            f'network.{IdType.NETWORK_DATA.value}.{NETWORK}',
        )

        config.server = PodServer(
            network, db_connection_string=os.environ['DB_CONNECTION']
        )
        config.server.network = network
        config.server.paths = network.paths

        await config.server.set_document_store(
            DocumentStoreType.OBJECT_STORE, cloud_type=CloudType('LOCAL'),
            private_bucket='byoda', restricted_bucket='byoda',
            public_bucket='byoda', root_dir=TEST_DIR
        )
        network.services_ca.validate(network.root_ca, with_openssl=True)
        network.accounts_ca.validate(network.root_ca, with_openssl=True)

        # Need to set role to allow loading of unsigned services
        network.roles = [ServerRole.Pod]

        service = Service(network=network)
        await service.examine_servicecontract(SCHEMA_FILE)
        await service.create_secrets(network.services_ca, local=True)

        services_ca: CaSecret = network.services_ca
        services_ca.validate(network.root_ca, with_openssl=True)
        service.service_ca.validate(network.root_ca, with_openssl=True)
        service.apps_ca.validate(network.root_ca, with_openssl=True)
        service.tls_secret.validate(network.root_ca, with_openssl=True)
        service.data_secret.validate(network.root_ca, with_openssl=True)

        account_id: UUID = get_test_uuid()
        account = Account(account_id, network)

        await account.paths.create_account_directory()

        config.server.account = account

        config.server.bootstrapping = True

        await account.create_secrets(network.accounts_ca)

        await config.server.set_data_store(
            DataStoreType.POSTGRES, account.data_secret
        )
        await config.server.set_cache_store(CacheStoreType.POSTGRES)

        account.tls_secret.validate(network.root_ca, with_openssl=True)
        account.data_secret.validate(network.root_ca, with_openssl=True)

    async def test_secrets(self) -> None:
        '''
        Test validation of cert chains and data encryption/decryption
        '''

        network: Network = await Network.create(NETWORK, TEST_DIR, 'byoda')
        config.server = PodServer(
            network, db_connection_string=os.environ['DB_CONNECTION']
        )
        config.server.network = network
        config.server.network.account = 'pod'

        await config.server.set_document_store(
            DocumentStoreType.OBJECT_STORE, cloud_type=CloudType('LOCAL'),
            private_bucket='byoda', restricted_bucket='byoda',
            public_bucket='byoda', root_dir=TEST_DIR
        )

        # Need to set role to allow loading of unsigned services
        network.roles = [ServerRole.Pod]

        shutil.copy(DEFAULT_SCHEMA, TEST_DIR + SCHEMA_FILE)
        service = Service(network=network)
        await service.examine_servicecontract(SCHEMA_FILE)
        await service.create_secrets(network.services_ca, local=True)

        account_id: UUID = get_test_uuid()
        account = Account(account_id, network)
        await account.paths.create_account_directory()
        await account.create_secrets(network.accounts_ca)

        config.server.account = account
        config.server.bootstrapping = True

        config.server.paths = network.paths
        await config.server.set_data_store(
            DataStoreType.POSTGRES, account.data_secret
        )
        await config.server.set_cache_store(CacheStoreType.POSTGRES)

        network.services_ca.validate(network.root_ca, with_openssl=True)
        network.accounts_ca.validate(network.root_ca, with_openssl=True)

        # Create a dummy entry for the services in the network, otherwise
        # account.join(service) fails
        network.services = {SERVICE_ID: service}

        target_dir: str = \
            f'/network-{NETWORK}/account-pod/service-{SERVICE_ID}'
        os.makedirs(TEST_DIR + target_dir)
        target_schema: str = target_dir + '/service-contract.json'
        shutil.copy(DEFAULT_SCHEMA, TEST_DIR + target_schema)

        # TODO: re-enable this test
        # member: Member = await account.join(
        #     SERVICE_ID, SCHEMA_VERSION, members_ca=service.members_ca,
        #     local_service_contract=SCHEMA_FILE,
        #     local_storage=config.server.storage_driver
        # )

        # self.assertIsNotNone(member.member_id)
        # member.tls_secret.validate(network.root_ca, with_openssl=True)
        # member.data_secret.validate(network.root_ca, with_openssl=True)

        # Certchain validation fails as network.services_ca
        # is not in the cert chain of account.data_secret and is
        # not the root CA
        with self.assertRaises(ValueError):
            account.data_secret.validate(network.services_ca)

        #
        # Test data encryption
        #
        target_account_id: UUID = get_test_uuid()
        target_account = Account(target_account_id, network, account='test')
        await target_account.paths.create_account_directory()
        await target_account.create_secrets(network.accounts_ca)

        account.data_secret.create_shared_key(target_account.data_secret)
        target_account.data_secret.load_shared_key(
            account.data_secret.protected_shared_key
        )

        self.assertEqual(
            account.data_secret.shared_key,
            target_account.data_secret.shared_key
        )

        with open('/etc/passwd', 'rb') as file_desc:
            data: bytes = file_desc.read()

        ciphertext: bytes = account.data_secret.encrypt(data)

        passwords: bytes = target_account.data_secret.decrypt(ciphertext)

        self.assertEqual(data, passwords)

        await account.create_secrets(network.accounts_ca, renew=True)

        # Test data encryption of large files
        source_file = TEST_DIR + 'bulk_data'
        with open(source_file, 'wb') as file_desc:
            data = secrets.token_bytes((1 << 21) - randint(1, 1 << 10))
            file_desc.write(data)

        protected_file = source_file + '.protected'
        out_file = source_file + '.out'

        data_secret: DataSecret = account.data_secret
        data_secret.create_shared_key()
        data_secret.encrypt_file(source_file, protected_file)
        data_secret.decrypt_file(protected_file, out_file)
        compare_check: bool = filecmp.cmp(source_file, out_file)
        self.assertTrue(compare_check)

        #
        # Tests for App secret
        #
        app_id: UUID = get_test_uuid()
        fqdn = 'testapp.com'
        app_secret = AppDataSecret(app_id, SERVICE_ID, network)
        csr: x509.CertificateSigningRequest = await app_secret.create_csr(fqdn)
        cert_chain: CertChain = service.apps_ca.sign_csr(csr)

        await cert_chain.save(
            app_secret.cert_file, config.server.storage_driver
        )

        #
        # Tests for App Data secret
        #
        app_data_secret = AppDataSecret(app_id, SERVICE_ID, network)
        csr = await app_data_secret.create_csr(fqdn)
        cert_chain = service.apps_ca.sign_csr(csr)

        await cert_chain.save(
            app_data_secret.cert_file, config.server.storage_driver
        )

        app_data_secret.cert = cert_chain.signed_cert

        #
        # Test claims
        #
        object_fields: list[str] = [
            'asset_id', 'asset_name', 'asset_type', 'asset_url',
            'creator', 'published_timestamp', 'annotations', 'creator',
        ]

        asset_id: UUID = get_test_uuid()
        requester_id: UUID = get_test_uuid()
        claim: Claim = Claim.build(
            ['claim A', 'claim B'], app_id, IdType.APP,
            'public_assets', 'asset_id', asset_id,
            object_fields, requester_id, IdType.MEMBER, 'https://signature',
            'https://renewal', 'https://confirmation'
        )
        asset_data: dict[str, any] = {
            'asset_id': asset_id,
            'asset_name': 'test asset',
            'asset_type': 'video',
            'asset_url': 'https://www.byoda.org',
            'creator': 'test',
            'published_timestamp': datetime.now(timezone.utc).isoformat(),
            'annotations': ['test1', 'test2'],
        }

        signature: str = claim.create_signature(asset_data, app_data_secret)

        verify_claim: Claim = Claim.build(
            ['claim A', 'claim B'], app_id, IdType.APP,
            'public_assets', 'asset_id', asset_id,
            object_fields, requester_id, IdType.MEMBER, 'https://signature',
            'https://renewal', 'https://confirmation'
        )
        verify_claim.claim_id = claim.claim_id
        verify_claim.signature_timestamp = claim.signature_timestamp
        verify_claim.signature_format_version = claim.signature_format_version
        verify_claim.cert_expiration = claim.cert_expiration
        verify_claim.cert_fingerprint = claim.cert_fingerprint

        verify_claim.signature = signature
        verify_claim.verify_signature(asset_data, app_data_secret)
        self.assertTrue(verify_claim.verified)

        data = claim.as_dict()
        new_claim: Claim = Claim.from_dict(data)
        new_claim.verify_signature(asset_data, app_data_secret)
        self.assertTrue(new_claim.verified)

    async def test_message_signature(self) -> None:
        # Test creation of the CA hierarchy
        network: Network = await Network.create(NETWORK, TEST_DIR, 'byoda')

        config.server = PodServer(
            network, db_connection_string=os.environ['DB_CONNECTION']
        )
        config.server.network = network
        await config.server.set_document_store(
            DocumentStoreType.OBJECT_STORE, cloud_type=CloudType('LOCAL'),
            private_bucket='byoda', restricted_bucket='byoda',
            public_bucket='byoda', root_dir=TEST_DIR
        )

        account = Account(get_test_uuid(), network)
        message = 'ik ben toch niet gek!'

        member_data_secret = MemberDataSecret(
            get_test_uuid(), ADDRESSBOOK_SERVICE_ID, account
        )
        member_data_secret.private_key = \
            member_data_secret.generate_private_key()
        member_data_secret.common_name = MemberDataSecret.create_common_name(
            member_data_secret.member_id, ADDRESSBOOK_SERVICE_ID, network
        )
        member_data_secret.create_selfsigned_cert()

        signature = member_data_secret.sign_message(message)
        member_data_secret.verify_message_signature(message, signature)

    async def test_tls_negotiation(self) -> None:
        '''
        Test TLS negotiation between network, service, and account
        '''

        network: Network = await Network.create(NETWORK, TEST_DIR, 'byoda')
        config.server = PodServer(
            network, db_connection_string=os.environ['DB_CONNECTION']
        )
        server: PodServer = config.server
        server.network = network
        server.network.account = 'pod'

        await server.set_document_store(
            DocumentStoreType.OBJECT_STORE, cloud_type=CloudType('LOCAL'),
            private_bucket='byoda', restricted_bucket='byoda',
            public_bucket='byoda', root_dir=TEST_DIR
        )

        # Need to set role to allow loading of unsigned services
        network.roles = [ServerRole.Pod]

        shutil.copy(DEFAULT_SCHEMA, TEST_DIR + SCHEMA_FILE)
        service = Service(network=network)
        await service.examine_servicecontract(SCHEMA_FILE)
        await service.create_secrets(network.services_ca, local=True)

        account_id: UUID = get_test_uuid()
        account = Account(account_id, network)
        await account.paths.create_account_directory()
        await account.create_secrets(network.accounts_ca)

        server.account = account
        server.bootstrapping = True

        server.paths = network.paths
        await server.set_data_store(
            DataStoreType.POSTGRES, account.data_secret
        )
        await config.server.set_cache_store(CacheStoreType.POSTGRES)

        conn = TlsConnection()
        server_task: asyncio.Task[None] = asyncio.create_task(
            conn.tls_server()
        )
        client_task: asyncio.Task[None] = asyncio.create_task(
            conn.tls_client(account.tls_secret)
        )
        await server_task
        await client_task

        # Test with data secret - should fail because 'unsuitable cert purpose'
        # Re-enable this test once we have figured out how to catch the
        # 'unsuitable cert purpose' exception raised by the TLS server in this
        # test case.
        # conn = TlsConnection()
        # server_task: asyncio.Task[None] = asyncio.create_task(
        #     conn.tls_server()
        # )
        # client_task: asyncio.Task[None] = asyncio.create_task(
        #     conn.tls_client(account.data_secret)
        # )
        # await server_task
        # with self.assertRaises(ssl.SSLCertVerificationError):
        #     await client_task


class TlsConnection:
    def __init__(self) -> None:
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._server: asyncio.Server | None = None

    @staticmethod
    async def get_context(tls_secret: Secret | None = None) -> ssl.SSLContext:
        server: PodServer = config.server
        network: Network = server.network
        root_ca: NetworkRootCaSecret = network.root_ca
        key_password: str = 'test'
        await root_ca.save(
            password=key_password, overwrite=True,
            storage_driver=server.local_storage,
        )

        base_dir: str = server.storage_driver.local_path
        if tls_secret:
            context: ssl.SSLContext = ssl.create_default_context(
                purpose=ssl.Purpose.SERVER_AUTH,
                cafile=base_dir + root_ca.cert_file
            )
            await tls_secret.save(
                password=key_password, overwrite=True,
                storage_driver=server.local_storage,
            )
            context.load_cert_chain(
                base_dir + tls_secret.cert_file,
                base_dir + tls_secret.private_key_file, key_password
            )
        else:
            context: ssl.SSLContext = ssl.create_default_context(
                purpose=ssl.Purpose.CLIENT_AUTH,
                cafile=base_dir + root_ca.cert_file
            )
            context.load_cert_chain(
                base_dir + root_ca.cert_file,
                base_dir + root_ca.private_key_file, key_password
            )

        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = False
        return context

    async def tls_server(self) -> None:
        async def handle_client(r: asyncio.StreamReader,
                                w: asyncio.StreamWriter) -> None:

            addr = w.get_extra_info('peername')
            print(f"Connection from {addr}")

            request: str = (await r.readline()).decode('utf8').rstrip()
            print(f'Read: {request}')
            data: bytes = await r.read(100)
            w.write(data)
            try:
                await w.drain()
            except ConnectionResetError:
                pass

            w.close()
            await w.wait_closed()
            self._shutdown_event.set()

        server_context: ssl.SSLContext = await TlsConnection.get_context()

        tls_server: asyncio.Server = await asyncio.start_server(
            handle_client, '127.0.0.1', 8888, ssl=server_context
        )

        serve_task: asyncio.Task[None] = asyncio.create_task(
            tls_server.serve_forever()
        )
        shutdown_task: asyncio.Task[Literal[True]] = asyncio.create_task(
            self._shutdown_event.wait()
        )

        await asyncio.wait(
            [serve_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        tls_server.close()
        await tls_server.wait_closed()

    async def tls_client(self, secret: Secret) -> None:
        await asyncio.sleep(1)  # Wait for server to start
        writer: asyncio.StreamWriter
        _, writer = await asyncio.open_connection('127.0.0.1', 8888)
        client_context: ssl.SSLContext = await TlsConnection.get_context(
            secret
        )

        try:
            await writer.start_tls(
                client_context, server_hostname='dir.byoda.net'
            )
        except ssl.SSLCertVerificationError as exc:
            print(f'TLS negotiation failed: {exc}')
            raise

        print(f"The server certificate is {writer.get_extra_info('peercert')}")

        writer.write(b'PING')
        await writer.drain()
        writer.close()
        await writer.wait_closed()


if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )

    unittest.main()
