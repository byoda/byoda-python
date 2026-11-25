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
from uuid import uuid4
from datetime import timedelta
from types import SimpleNamespace
from ipaddress import ip_address

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service

from byoda.datastore.certstore import CertStore

from byoda.datatypes import IdType
from byoda.datatypes import ServerRole

from byoda.secrets.secret import Secret
from byoda.secrets.ca_secret import CaSecret
from byoda.secrets.networkservicesca_secret import NetworkServicesCaSecret
from byoda.secrets.serviceca_secret import ServiceCaSecret
from byoda.secrets.membersca_secret import MembersCaSecret
from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.account_secret import AccountSecret

from byoda.util.logger import Logger as ByodaLogger

TEST_DIR: str = '/tmp/byoda-tests/cert-lifetimes'
NETWORK: str = 'test.net'
SERVICE_ID: int = 1234

CA_LOGGER: str = 'byoda.secrets.ca_secret'

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
        with self.assertRaises(ValueError):
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


if __name__ == '__main__':
    ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
