#!/usr/bin/env python3


from cryptography import x509
from cryptography import exceptions as crypto_exceptions
from cryptography.x509.base import Certificate

with open('tests/collateral/expired-service-ca-cert.pem', 'rb') as f:
    expired_service_ca_cert: bytes = f.read()


cert: Certificate = x509.load_pem_x509_certificate(expired_service_ca_cert)
print(cert)
