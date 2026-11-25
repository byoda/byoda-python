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

from byoda.datamodel.network import Network

from byoda.secrets.secret import Secret
from byoda.secrets.ca_secret import CaSecret
from byoda.secrets.networkservicesca_secret import NetworkServicesCaSecret
from byoda.secrets.serviceca_secret import ServiceCaSecret
from byoda.secrets.membersca_secret import MembersCaSecret
from byoda.secrets.member_secret import MemberSecret

from byoda.util.logger import Logger as ByodaLogger

TEST_DIR: str = '/tmp/byoda-tests/cert-lifetimes'
NETWORK: str = 'test.net'
SERVICE_ID: int = 1234

CA_LOGGER: str = 'byoda.secrets.ca_secret'


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


if __name__ == '__main__':
    ByodaLogger.getLogger(sys.argv[0], debug=True, json_out=False)

    unittest.main()
