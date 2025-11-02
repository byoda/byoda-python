#!/usr/bin/env python3

'''
Test the DnsDB class against Postgres server for byoda.net

TODO: test case stopped passing since migration of postgres server to the
cloud, likely because the 'test.net' domain was not created.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license
'''

import sys
import yaml
import asyncio
import unittest

from logging import Logger
from ipaddress import IPv4Address, IPv6Address, ip_address

import dns.resolver

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

from byoda.config import DEFAULT_NETWORK

from byoda.datatypes import IdType
from byoda.datastore.dnsdb import DnsRecordType

from byoda.datastore.dnsdb import DnsDb

from byoda.util.logger import Logger as ByodaLogger

CONFIG = 'tests/collateral/config.yml'
TEST_DIR = '/tmp/byoda-func-test-secrets'
NETWORK: str = DEFAULT_NETWORK
DNS_CACHE_PERIOD = 300
DNS_CHANGE_LATENCY = 300

TEST_SERVICE_ID = 4294967295
TEST_MEMBER_UUID = 'aaaaaaaa-fe4a-1f0b-2d2f-30808f40d0fd'
TEST_SERVICE_UUID = 'aaaaaaaa-f171-4f0b-8d2f-d0808f40d0fd'
TEST_ACCOUNT_UUID = 'aaaaaaaa-a246-ea54-8d2f-c3658f40d0fd'
TEST_FIRST_IP = '10.255.255.254'
TEST_SECOND_IP = '10.255.255.253'
TEST_NETWORK = None


class TestDnsDb(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await delete_test_data()

    async def test_dnsdb(self) -> None:
        with open(CONFIG) as file_desc:
            config: dict[str, any] = yaml.load(
                file_desc, Loader=yaml.SafeLoader
            )

        global TEST_NETWORK
        TEST_NETWORK = config['application']['network']

        dnsdb: DnsDb = await DnsDb.setup(
            config['dirserver']['dnsdb'], TEST_NETWORK
        )

        # SERVICE
        service_id: int = TEST_SERVICE_ID
        first_ip: IPv4Address | IPv6Address = ip_address(TEST_FIRST_IP)
        second_ip: IPv4Address | IPv6Address = ip_address(TEST_SECOND_IP)

        service_fqdn: str = dnsdb.compose_fqdn(
            None, IdType.SERVICE, service_id=service_id
        )
        self.assertEqual(
            service_fqdn,
            f'service.service-{str(service_id)}.{TEST_NETWORK}'
        )

        with self.assertRaises(KeyError):
            await dnsdb.lookup(
                None, IdType.SERVICE, DnsRecordType.A,
                service_id=service_id
            )

        await dnsdb.create_update(
            None, IdType.SERVICE, first_ip,
            service_id=service_id
        )

        self.assertEqual(
            await dnsdb.lookup(
                None, IdType.SERVICE, DnsRecordType.A,
                service_id=service_id
            ), first_ip
        )

        await dnsdb.create_update(
            None, IdType.SERVICE, first_ip,
            service_id=service_id
        )

        self.assertEqual(
            await dnsdb.lookup(
                None, IdType.SERVICE, DnsRecordType.A,
                service_id=service_id
            ), first_ip
        )

        await dnsdb.create_update(
            None, IdType.SERVICE, second_ip,
            service_id=service_id
        )

        await dnsdb.create_update(
            None, IdType.SERVICE, second_ip,
            service_id=service_id
        )

        self.assertIn(
            await dnsdb.lookup(
                None, IdType.SERVICE, DnsRecordType.A,
                service_id=service_id
            ), [first_ip, second_ip]
        )

        await dnsdb.remove(
            None, IdType.SERVICE, DnsRecordType.A,
            service_id=service_id
        )

        with self.assertRaises(KeyError):
            await dnsdb.lookup(
                None, IdType.SERVICE, DnsRecordType.A,
                service_id=service_id
            )

        # MEMBER
        uuid = TEST_MEMBER_UUID
        member: str = dnsdb.compose_fqdn(
            uuid, IdType.MEMBER, service_id=service_id
        )
        self.assertEqual(
            member, f'{str(uuid)}.members-{service_id}.{TEST_NETWORK}'
        )

        with self.assertRaises(KeyError):
            await dnsdb.lookup(
                uuid, IdType.MEMBER, DnsRecordType.A,
                service_id=service_id
            )

        await dnsdb.create_update(
            uuid, IdType.MEMBER, first_ip,
            service_id=service_id
        )

        self.assertEqual(
            await dnsdb.lookup(
                uuid, IdType.MEMBER, DnsRecordType.A,
                service_id=service_id
            ),
            first_ip
        )

        await dnsdb.create_update(
            uuid, IdType.MEMBER, first_ip,
            service_id=service_id
        )

        self.assertEqual(
            await dnsdb.lookup(
                uuid, IdType.MEMBER, DnsRecordType.A,
                service_id=service_id
            ),
            first_ip
        )

        await dnsdb.create_update(
            uuid, IdType.MEMBER, second_ip,
            service_id=service_id
        )

        self.assertIn(
            await dnsdb.lookup(
                uuid, IdType.MEMBER, DnsRecordType.A,
                service_id=service_id
            ),
            [first_ip, second_ip]
        )
        await dnsdb.remove(
            uuid, IdType.MEMBER, DnsRecordType.A,
            service_id=service_id
        )

        with self.assertRaises(KeyError):
            await dnsdb.lookup(
                uuid, IdType.MEMBER, DnsRecordType.A,
                service_id=service_id
            )

        # ACCOUNT
        uuid = TEST_ACCOUNT_UUID
        account: str = dnsdb.compose_fqdn(uuid, IdType.ACCOUNT)
        self.assertEqual(account, f'{str(uuid)}.accounts.{TEST_NETWORK}')

        with self.assertRaises(KeyError):
            await dnsdb.lookup(
                uuid, IdType.ACCOUNT, DnsRecordType.A,
            )

        fqdn: str = dnsdb.compose_fqdn(uuid, IdType.ACCOUNT)

        await dnsdb.create_update(
            uuid, IdType.ACCOUNT, first_ip,
        )

        self.assertEqual(await dnsdb.lookup(
                uuid, IdType.ACCOUNT, DnsRecordType.A,
            ), first_ip
        )

        dns_ip = await do_dns_lookup(fqdn)
        self.assertIn(dns_ip, [first_ip, second_ip])

        second_ip = ip_address(TEST_SECOND_IP)
        await dnsdb.create_update(
            uuid, IdType.ACCOUNT, second_ip
        )

        self.assertIn(
            await dnsdb.lookup(
                uuid, IdType.ACCOUNT, DnsRecordType.A
            ),
            [first_ip, second_ip]
        )

        dns_ip: IPv4Address | IPv6Address = await do_dns_lookup(fqdn)
        self.assertIn(dns_ip, [first_ip, second_ip])

        await dnsdb.remove(uuid, IdType.ACCOUNT, DnsRecordType.A)
        with self.assertRaises(dns.resolver.NXDOMAIN):
            await do_dns_lookup(
                fqdn,  expect_success=False, timeout=DNS_CHANGE_LATENCY * 2
            )


async def do_dns_lookup(fqdn, expect_success: bool = True,
                        timeout: int = DNS_CHANGE_LATENCY) -> IPv4Address:
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ['192.168.1.13']        # dir.byoda.net
    resolver.timeout = 5
    resolver.lifetime = 60

    wait_interval: int = 10
    _LOGGER.debug(f'Starting DNS lookup for {fqdn}...')
    if expect_success:
        return await do_dns_lookup_success(
            fqdn, resolver, wait_interval, timeout
        )
    else:
        await do_dns_lookup_failure(fqdn, resolver, wait_interval, timeout)


async def do_dns_lookup_success(fqdn: str, resolver: dns.resolver.Resolver,
                                wait_interval: int, timeout: int
                                ) -> IPv4Address | IPv6Address:
    answer: dns.resolver.Answer | None = None
    wait_time: int = 0
    while not answer and wait_time < timeout:
        try:
            answer: dns.resolver.Answer = resolver.resolve(fqdn)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers,
                dns.resolver.NoAnswer):
            wait_time += 10
            _LOGGER.debug(
                f'Waiting {wait_interval} seconds for DNS change to propagate.'
                f' Already waited {wait_time} seconds...'
            )
            await asyncio.sleep(wait_interval)

    if not answer:
        raise RuntimeError(
            f'DNS lookup failed after waiting for {wait_time} seconds'
        )

    dns_ip: IPv4Address | IPv6Address = ip_address(
        list(answer.rrset.items.keys())[0].address
    )

    return dns_ip


async def do_dns_lookup_failure(fqdn: str, resolver: dns.resolver.Resolver,
                                wait_interval: int, timeout: int) -> None:
    wait_time: int = 0
    answer: dns.resolver.Answer | None = IPv4Address('0.0.0.0')
    while answer and wait_time < timeout:
        answer = resolver.resolve(fqdn)
        wait_time += 10
        _LOGGER.debug(
            f'Waiting {wait_interval} seconds for DNS change to propagate. '
            f'Already waited {wait_time} seconds...'
        )
        await asyncio.sleep(wait_interval)

    if answer:
        raise RuntimeError(f'DNS entry still exists: {answer}')


async def delete_test_data() -> None:
    with open(CONFIG) as file_desc:
        config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    global TEST_NETWORK
    TEST_NETWORK = config['application']['network']

    connection_string: str = config['dirserver']['dnsdb']
    pool: AsyncConnectionPool = AsyncConnectionPool(
        conninfo=connection_string, open=False,
        kwargs={'row_factory': dict_row}
    )
    await pool.open()

    async with pool.connection() as conn:
        await conn.execute(
            'DELETE FROM domains WHERE name != %s', [f'{TEST_NETWORK}']
        )

        await conn.execute(
            'DELETE FROM records WHERE name != %s', [f'{TEST_NETWORK}']
        )

    await pool.close()

if __name__ == '__main__':
    _LOGGER: Logger = ByodaLogger.getLogger(
        sys.argv[0], debug=True, json_out=False
    )
    unittest.main()
