#!/usr/bin/env python3

'''
Test the SSL context that the API clients use for mTLS

httpx2 only uses a client cert when it is loaded into the SSLContext passed
as 'verify'. Passing 'cert=' with 'verify=None' fails with an AttributeError
and with 'verify=<path>' fails with a TypeError.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import os
import ssl
import shutil
import unittest
import tempfile

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from httpx2 import Client as SyncHttpClient
from httpx2 import AsyncClient as AsyncHttpClient

from byoda.util.api_client.api_client import create_ssl_context


def _write_selfsigned(directory: str, name: str) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now: datetime = datetime.now(tz=timezone.utc)
    cert: x509.Certificate = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(key, hashes.SHA256())
    )
    cert_file: str = os.path.join(directory, f'{name}-cert.pem')
    key_file: str = os.path.join(directory, f'{name}.key')
    with open(cert_file, 'wb') as file_desc:
        file_desc.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_file, 'wb') as file_desc:
        file_desc.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()
            )
        )
    return cert_file, key_file


class TestCreateSslContext(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir: str = tempfile.mkdtemp()
        self.ca_file, _ = _write_selfsigned(self.tmpdir, 'test-root-ca')
        self.cert = _write_selfsigned(self.tmpdir, 'test-client')

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir)

    def test_ca_file_is_trusted(self) -> None:
        ctx: ssl.SSLContext = create_ssl_context(self.ca_file, None)
        subjects: list = [
            dict(rdn[0] for rdn in ca['subject'])['commonName']
            for ca in ctx.get_ca_certs()
        ]
        self.assertEqual(subjects, ['test-root-ca'])
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_without_ca_file_verifies_server(self) -> None:
        ctx: ssl.SSLContext = create_ssl_context(None, None)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_client_cert_is_loaded(self) -> None:
        create_ssl_context(self.ca_file, self.cert)
        create_ssl_context(None, self.cert)

    def test_bad_client_cert_raises(self) -> None:
        with self.assertRaises((ssl.SSLError, OSError)):
            create_ssl_context(None, (self.ca_file, self.ca_file))

    def test_httpx2_clients_accept_context_with_client_cert(self) -> None:
        for ca_file in (self.ca_file, None):
            ctx: ssl.SSLContext = create_ssl_context(ca_file, self.cert)
            AsyncHttpClient(verify=ctx, http2=False)
            SyncHttpClient(verify=ctx, http2=False)


if __name__ == '__main__':
    unittest.main()
