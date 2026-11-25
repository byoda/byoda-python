#!/usr/bin/env python3

'''
Test cases for certificate lifetimes, the issuer-expiry cap, the
EC P-256 requirement for CSRs and certificate renewal warnings

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2026
:license    : GPLv3
'''

import sys
import shutil
import asyncio
import unittest

from copy import copy
from unittest.mock import patch
from uuid import uuid4
from datetime import datetime
from datetime import timedelta
from types import SimpleNamespace
from ipaddress import ip_address

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric import ed25519

from fastapi import HTTPException

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service

from byoda.datastore.certstore import CertStore

from byoda.datatypes import IdType
from byoda.datatypes import ServerRole

from byoda.exceptions import ByodaCaExpiredError

from byoda.secrets.secret import Secret
from byoda.secrets.ca_secret import CaSecret
from byoda.secrets.networkservicesca_secret import NetworkServicesCaSecret
from byoda.secrets.serviceca_secret import ServiceCaSecret
from byoda.secrets.membersca_secret import MembersCaSecret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.account_secret import AccountSecret
from byoda.secrets.appsca_secret import AppsCaSecret

from byoda.util.logger import Logger as ByodaLogger

TEST_DIR: str = '/tmp/byoda-tests/cert-lifetimes'
NETWORK: str = 'test.net'
SERVICE_ID: int = 1234

CA_LOGGER: str = 'byoda.secrets.ca_secret'
SECRET_LOGGER: str = 'byoda.secrets.secret'

SCHEMA_FILE: str = 'addressbook.json'

# Lifetimes in days, from the design for the byoda.net reset
ROOT_CA_DAYS: int = 100 * 365
NETWORK_INTERMEDIATE_DAYS: int = 5 * 365
SERVICE_CA_DAYS: int = 4 * 365
SERVICE_SUB_CA_DAYS: int = 3 * 365
END_ENTITY_DAYS: int = 365

LOCALHOST = ip_address('127.0.0.1')


def lifetime_days(secret: Secret) -> float:
    '''
    Returns the validity period of the cert of the secret, in days
    '''

    cert = secret.cert
    delta: timedelta = cert.not_valid_after_utc - cert.not_valid_before_utc
    return delta.total_seconds() / 86400


async def make_network() -> Network:
    '''
    Creates a new network with all its secrets in an empty TEST_DIR
    '''

    shutil.rmtree(TEST_DIR, ignore_errors=True)
    return await Network.create(NETWORK, TEST_DIR, 'byoda')


def network_namespace(network: Network) -> SimpleNamespace:
    '''
    Some secret classes modify the paths of the network they are given,
    so each one gets its own copy
    '''

    return SimpleNamespace(name=NETWORK, paths=copy(network.paths))


async def make_service(network: Network) -> Service:
    '''
    Creates the secrets of the addressbook service, signing the service CA
    locally with the network services CA
    '''

    shutil.copy(f'tests/collateral/{SCHEMA_FILE}', f'{TEST_DIR}/{SCHEMA_FILE}')

    # Allows loading of a service contract without network signature
    network.roles = [ServerRole.Pod]

    service = Service(network=network)
    await service.examine_servicecontract(SCHEMA_FILE)
    await service.create_secrets(network.services_ca, local=True)

    return service


async def sign_short_services_ca(network: Network,
                                 expire: int | timedelta
                                 ) -> NetworkServicesCaSecret:
    '''
    Creates a network services CA with a short lifetime, signed by
    the root CA of the network
    '''

    short_ca = NetworkServicesCaSecret(copy(network.paths))
    csr = await short_ca.create_csr()
    short_ca.from_signed_cert(network.root_ca.sign_csr(csr, expire=expire))

    return short_ca


async def sign_service_ca(issuing_ca: CaSecret, network: Network
                          ) -> ServiceCaSecret:
    service_ca = ServiceCaSecret(SERVICE_ID, network_namespace(network))
    csr = await service_ca.create_csr()
    service_ca.from_signed_cert(issuing_ca.sign_csr(csr))

    return service_ca


class TestIssuerCap(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.network: Network = await make_network()

    async def test_child_capped_to_short_lived_issuer(self) -> None:
        short_ca = await sign_short_services_ca(self.network, 30)

        with self.assertLogs(CA_LOGGER, 'WARNING'):
            service_ca = await sign_service_ca(short_ca, self.network)

        self.assertEqual(
            service_ca.cert.not_valid_after_utc,
            short_ca.cert.not_valid_after_utc
        )

    async def test_cap_is_transitive(self) -> None:
        short_ca = await sign_short_services_ca(self.network, 30)
        service_ca = await sign_service_ca(short_ca, self.network)

        members_ca = MembersCaSecret(
            SERVICE_ID, network_namespace(self.network)
        )
        csr = await members_ca.create_csr()
        members_ca.from_signed_cert(service_ca.sign_csr(csr))

        member = MemberSecret(
            uuid4(), SERVICE_ID, paths=copy(self.network.paths),
            network_name=NETWORK
        )
        csr = await member.create_csr()
        member.from_signed_cert(members_ca.sign_csr(csr))

        limit = short_ca.cert.not_valid_after_utc
        chain: list[tuple[Secret, Secret]] = [
            (service_ca, short_ca),
            (members_ca, service_ca),
            (member, members_ca),
        ]
        for child, issuer in chain:
            self.assertLessEqual(
                child.cert.not_valid_after_utc,
                issuer.cert.not_valid_after_utc
            )
            self.assertLessEqual(child.cert.not_valid_after_utc, limit)

    async def test_explicit_expire_is_capped(self) -> None:
        short_ca = await sign_short_services_ca(self.network, 30)

        service_ca = ServiceCaSecret(
            SERVICE_ID, network_namespace(self.network)
        )
        csr = await service_ca.create_csr()
        service_ca.from_signed_cert(short_ca.sign_csr(csr, expire=10 * 365))

        self.assertEqual(
            service_ca.cert.not_valid_after_utc,
            short_ca.cert.not_valid_after_utc
        )

    async def test_expired_issuer_raises(self) -> None:
        short_ca = await sign_short_services_ca(
            self.network, timedelta(seconds=1)
        )
        await asyncio.sleep(1.5)

        service_ca = ServiceCaSecret(
            SERVICE_ID, network_namespace(self.network)
        )
        csr = await service_ca.create_csr()
        with self.assertRaises(ByodaCaExpiredError):
            short_ca.sign_csr(csr)


class TestCreatedLifetimes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.network: Network = await make_network()

    def assertLifetime(self, secret: Secret, days: int) -> None:
        self.assertAlmostEqual(
            lifetime_days(secret), days, delta=1,
            msg=f'{type(secret).__name__} has wrong lifetime'
        )

    async def test_network_create(self) -> None:
        self.assertLifetime(self.network.root_ca, ROOT_CA_DAYS)
        self.assertLifetime(
            self.network.accounts_ca, NETWORK_INTERMEDIATE_DAYS
        )
        self.assertLifetime(
            self.network.services_ca, NETWORK_INTERMEDIATE_DAYS
        )
        self.assertLifetime(
            self.network.data_secret, NETWORK_INTERMEDIATE_DAYS
        )

    async def test_service_create_secrets(self) -> None:
        service: Service = await make_service(self.network)

        self.assertLifetime(service.service_ca, SERVICE_CA_DAYS)
        self.assertLifetime(service.members_ca, SERVICE_SUB_CA_DAYS)
        self.assertLifetime(service.apps_ca, SERVICE_SUB_CA_DAYS)
        self.assertLifetime(service.tls_secret, END_ENTITY_DAYS)
        self.assertLifetime(service.data_secret, END_ENTITY_DAYS)

    async def test_certstore_sign(self) -> None:
        service: Service = await make_service(self.network)

        cases: list[tuple[CaSecret, Secret, IdType, int]] = [
            (
                self.network.services_ca,
                ServiceCaSecret(SERVICE_ID, network_namespace(self.network)),
                IdType.SERVICE_CA, SERVICE_CA_DAYS
            ),
            (
                self.network.accounts_ca,
                AccountSecret(
                    account_id=uuid4(), network=network_namespace(self.network)
                ),
                IdType.ACCOUNT, END_ENTITY_DAYS
            ),
            (
                service.members_ca,
                MemberSecret(
                    uuid4(), service.service_id,
                    paths=copy(self.network.paths), network_name=NETWORK
                ),
                IdType.MEMBER, END_ENTITY_DAYS
            ),
        ]
        for ca, secret, id_type, days in cases:
            csr = await secret.create_csr()
            certchain = CertStore(ca).sign(
                secret.csr_as_pem(csr), id_type, LOCALHOST
            )
            secret.from_signed_cert(certchain)
            self.assertLifetime(secret, days)


def service_ca_csr_with_key(private_key) -> x509.CertificateSigningRequest:
    '''
    Builds a CSR for a valid service CA common name, signed with the
    provided private key
    '''

    common_name: str = f'service-ca.service-ca-{SERVICE_ID}.{NETWORK}'
    algorithm = None
    if not isinstance(private_key, ed25519.Ed25519PrivateKey):
        algorithm = hashes.SHA256()

    return x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(common_name)]),
        critical=False
    ).add_extension(
        x509.BasicConstraints(ca=True, path_length=None), critical=True
    ).sign(private_key, algorithm)


class TestEcOnly(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.network: Network = await make_network()

    def assert_rejected(self, private_key, regex: str) -> None:
        csr = service_ca_csr_with_key(private_key)
        services_ca = self.network.services_ca

        with self.assertRaisesRegex(ValueError, regex):
            services_ca.review_csr(csr)

        pem: str = csr.public_bytes(serialization.Encoding.PEM).decode()
        with self.assertRaisesRegex(ValueError, regex):
            CertStore(services_ca).sign(pem, IdType.SERVICE_CA, LOCALHOST)

    async def test_rejects_rsa_csr(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.assert_rejected(key, 'EC P-256')

    async def test_rejects_ed25519_csr(self) -> None:
        self.assert_rejected(
            ed25519.Ed25519PrivateKey.generate(), 'EC P-256'
        )

    async def test_rejects_p384_csr(self) -> None:
        self.assert_rejected(
            ec.generate_private_key(ec.SECP384R1()), 'EC P-256'
        )

    async def test_rejects_p521_csr(self) -> None:
        self.assert_rejected(
            ec.generate_private_key(ec.SECP521R1()), 'EC P-256'
        )

    async def test_all_generated_keys_are_p256(self) -> None:
        service: Service = await make_service(self.network)

        secrets: list[Secret] = [
            self.network.root_ca, self.network.accounts_ca,
            self.network.services_ca, self.network.data_secret,
            service.service_ca, service.members_ca, service.apps_ca,
            service.tls_secret, service.data_secret,
        ]
        for secret in secrets:
            self.assertEqual(
                secret.cert.public_key().curve.name, 'secp256r1',
                msg=f'{type(secret).__name__} is not EC P-256'
            )


class TestRenewalThresholds(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.network: Network = await make_network()
        self.service: Service = await make_service(self.network)

    async def make_member(self, expire: int | None = None) -> MemberSecret:
        member = MemberSecret(
            uuid4(), self.service.service_id,
            paths=copy(self.network.paths), network_name=NETWORK
        )
        csr = await member.create_csr()
        member.from_signed_cert(
            self.service.members_ca.sign_csr(csr, expire=expire)
        )
        return member

    async def test_leaf_needed_warns(self) -> None:
        member: MemberSecret = await self.make_member(expire=20)
        with self.assertLogs(SECRET_LOGGER, 'WARNING'):
            member.review_expiration()

    async def test_leaf_wanted_info(self) -> None:
        member: MemberSecret = await self.make_member(expire=100)
        with self.assertLogs(SECRET_LOGGER, 'INFO') as logs:
            member.review_expiration()

        levels: set[str] = {record.levelname for record in logs.records}
        self.assertEqual(levels, {'INFO'})

    async def test_apps_ca_needed_warns(self) -> None:
        apps_ca = AppsCaSecret(
            self.service.service_id, network_namespace(self.network)
        )
        csr = await apps_ca.create_csr()
        apps_ca.from_signed_cert(
            self.service.service_ca.sign_csr(csr, expire=60)
        )
        with self.assertLogs(SECRET_LOGGER, 'WARNING'):
            apps_ca.review_expiration()

    async def test_ca_quiet_when_fresh(self) -> None:
        with self.assertNoLogs(SECRET_LOGGER, 'INFO'):
            self.network.services_ca.review_expiration()

    async def test_thresholds_use_current_time(self) -> None:
        member: MemberSecret = await self.make_member()

        class FutureDatetime(datetime):
            @classmethod
            def now(cls, tz=None) -> datetime:
                return datetime.now(tz=tz) + timedelta(days=340)

        with patch('byoda.secrets.secret.datetime', FutureDatetime):
            with self.assertLogs(SECRET_LOGGER, 'WARNING'):
                member.review_expiration()


class TestSignForApi(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.network: Network = await make_network()

    async def test_rejected_csr_is_http_400_with_reason(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = service_ca_csr_with_key(key)
        pem: str = csr.public_bytes(serialization.Encoding.PEM).decode()

        with self.assertRaises(HTTPException) as ctx:
            CertStore(self.network.services_ca).sign_for_api(
                pem, IdType.SERVICE_CA, LOCALHOST
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('EC P-256', ctx.exception.detail)

    async def test_expired_ca_is_http_503(self) -> None:
        short_ca = await sign_short_services_ca(
            self.network, timedelta(seconds=1)
        )
        await asyncio.sleep(1.5)

        service_ca = ServiceCaSecret(
            SERVICE_ID, network_namespace(self.network)
        )
        csr = await service_ca.create_csr()

        with self.assertRaises(HTTPException) as ctx:
            CertStore(short_ca).sign_for_api(
                service_ca.csr_as_pem(csr), IdType.SERVICE_CA, LOCALHOST
            )

        self.assertEqual(ctx.exception.status_code, 503)

    async def test_valid_csr_is_signed(self) -> None:
        service_ca = ServiceCaSecret(
            SERVICE_ID, network_namespace(self.network)
        )
        csr = await service_ca.create_csr()

        certchain = CertStore(self.network.services_ca).sign_for_api(
            service_ca.csr_as_pem(csr), IdType.SERVICE_CA, LOCALHOST
        )
        service_ca.from_signed_cert(certchain)

        self.assertAlmostEqual(
            lifetime_days(service_ca), SERVICE_CA_DAYS, delta=1
        )


if __name__ == '__main__':
    ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
