#!/usr/bin/env python3

'''
Test the DnsDB class against Postgres server for byoda.net

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

import sys
import yaml
import asyncio
import unittest
from ipaddress import ip_address

import dns.resolver

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from byoda.util.logger import Logger
from byoda.config import DEFAULT_NETWORK

from byoda.datatypes import IdType
from byoda.datastore.dnsdb import DnsRecordType

from byoda.datastore.dnsdb import DnsDb


# CONFIG = 'tests/collateral/config-dnsdb-test.yml'
CONFIG = 'tests/collateral/config.yml'
TEST_DIR = '/tmp/byoda-func-test-secrets'
NETWORK = DEFAULT_NETWORK
DNS_CACHE_PERIOD = 300

TEST_SERVICE_ID = 4294967295
TEST_MEMBER_UUID = 'aaaaaaaa-fe4a-1f0b-2d2f-30808f40d0fd'
TEST_SERVICE_UUID = 'aaaaaaaa-f171-4f0b-8d2f-d0808f40d0fd'
TEST_ACCOUNT_UUID = 'aaaaaaaa-a246-ea54-8d2f-c3658f40d0fd'
TEST_FIRST_IP = '10.255.255.254'
TEST_SECOND_IP = '10.255.255.253'
TEST_NETWORK = None


class TestDnsDb(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Logger.getLogger(sys.argv[0], debug=True, json_out=False)

        await delete_test_data()

    async def test_dnsdb(self):
        with open(CONFIG) as file_desc:
            config = yaml.load(file_desc, Loader=yaml.SafeLoader)

        global TEST_NETWORK
        TEST_NETWORK = config['application']['network']

        dnsdb = await DnsDb.setup(
            config['dirserver']['dnsdb'], TEST_NETWORK
        )

        async with dnsdb.async_session() as db_session:
            # SERVICE
            uuid = TEST_SERVICE_UUID
            service_id = TEST_SERVICE_ID
            first_ip = ip_address(TEST_FIRST_IP)
            second_ip = ip_address(TEST_SECOND_IP)

            service_fqdn = dnsdb.compose_fqdn(
                None, IdType.SERVICE, service_id=service_id
            )
            self.assertEqual(
                service_fqdn,
                f'service.service-{str(service_id)}.{TEST_NETWORK}'
            )

            with self.assertRaises(KeyError):
                await dnsdb.lookup(
                    None, IdType.SERVICE, DnsRecordType.A, db_session,
                    service_id=service_id
                )

            self.assertFalse(
                await dnsdb.create_update(
                    None, IdType.SERVICE, first_ip, db_session,
                    service_id=service_id
                )
            )
            self.assertEqual(
                await dnsdb.lookup(
                    None, IdType.SERVICE, DnsRecordType.A, db_session,
                    service_id=service_id
                ), first_ip
            )

            self.assertFalse(
                await dnsdb.create_update(
                    None, IdType.SERVICE, first_ip, db_session,
                    service_id=service_id
                )
            )

            self.assertEqual(
                await dnsdb.lookup(
                    None, IdType.SERVICE, DnsRecordType.A, db_session,
                    service_id=service_id
                ), first_ip
            )

            self.assertTrue(
                await dnsdb.create_update(
                    None, IdType.SERVICE, second_ip, db_session,
                    service_id=service_id
                )
            )

            self.assertEqual(
                await dnsdb.lookup(
                    None, IdType.SERVICE, DnsRecordType.A, db_session,
                    service_id=service_id
                ), second_ip
            )

            await dnsdb.remove(
                None, IdType.SERVICE, DnsRecordType.A, db_session,
                service_id=service_id
            )

            with self.assertRaises(KeyError):
                await dnsdb.lookup(
                    None, IdType.SERVICE, DnsRecordType.A, db_session,
                    service_id=service_id
                )

            # MEMBER
            uuid = TEST_MEMBER_UUID
            member = dnsdb.compose_fqdn(
                uuid, IdType.MEMBER, service_id=service_id
            )
            self.assertEqual(
                member, f'{str(uuid)}.members-{service_id}.{TEST_NETWORK}'
            )

            with self.assertRaises(KeyError):
                await dnsdb.lookup(
                    uuid, IdType.MEMBER, DnsRecordType.A, db_session,
                    service_id=service_id
                )

            self.assertFalse(
                await dnsdb.create_update(
                    uuid, IdType.MEMBER, first_ip, db_session,
                    service_id=service_id
                )
            )

            self.assertEqual(
                await dnsdb.lookup(
                    uuid, IdType.MEMBER, DnsRecordType.A, db_session,
                    service_id=service_id
                ),
                first_ip
            )

            self.assertFalse(
                await dnsdb.create_update(
                    uuid, IdType.MEMBER, first_ip, db_session,
                    service_id=service_id
                )
            )

            self.assertEqual(
                await dnsdb.lookup(
                    uuid, IdType.MEMBER, DnsRecordType.A, db_session,
                    service_id=service_id
                ),
                first_ip
            )

            self.assertTrue(
                await dnsdb.create_update(
                    uuid, IdType.MEMBER, second_ip, db_session,
                    service_id=service_id
                )
            )

            self.assertEqual(
                await dnsdb.lookup(
                    uuid, IdType.MEMBER, DnsRecordType.A, db_session,
                    service_id=service_id
                ),
                second_ip
            )
            await dnsdb.remove(
                uuid, IdType.MEMBER, DnsRecordType.A, db_session,
                service_id=service_id
            )

            with self.assertRaises(KeyError):
                await dnsdb.lookup(
                    uuid, IdType.MEMBER, DnsRecordType.A, db_session,
                    service_id=service_id
                )

            # ACCOUNT
            uuid = TEST_ACCOUNT_UUID
            account = dnsdb.compose_fqdn(uuid, IdType.ACCOUNT)
            self.assertEqual(account, f'{str(uuid)}.accounts.{TEST_NETWORK}')

            with self.assertRaises(KeyError):
                await dnsdb.lookup(
                    uuid, IdType.ACCOUNT, DnsRecordType.A, db_session
                )

            fqdn = dnsdb.compose_fqdn(uuid, IdType.ACCOUNT)

            self.assertFalse(
                await dnsdb.create_update(
                    uuid, IdType.ACCOUNT, first_ip, db_session
                )
            )
            self.assertEqual(
                first_ip, await dnsdb.lookup(
                    uuid, IdType.ACCOUNT, DnsRecordType.A, db_session
                )
            )

            dns_ip = do_dns_lookup(fqdn)
            self.assertEqual(dns_ip, first_ip)

            second_ip = ip_address(TEST_SECOND_IP)
            self.assertTrue(
                await dnsdb.create_update(
                    uuid, IdType.ACCOUNT, second_ip, db_session
                )
            )
            dns_ip = do_dns_lookup(fqdn)
            self.assertEqual(
                second_ip,
                await dnsdb.lookup(
                    uuid, IdType.ACCOUNT, DnsRecordType.A, db_session
                )
            )

            await asyncio.sleep(DNS_CACHE_PERIOD + 1)

            dns_ip = do_dns_lookup(fqdn)
            self.assertEqual(dns_ip, second_ip)

        # TODO Packet and record caching of PowerDNS likely makes this test
        # fail

        # time.sleep(DNS_CACHE_PERIOD + 1)
        # with self.assertRaises(dns.resolver.NXDOMAIN):
        #    do_dns_lookup(fqdn)

        dnsdb._engine.dispose()


def do_dns_lookup(fqdn):
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ['104.42.73.223']        # dir.byoda.net
    resolver.timeout = 1
    resolver.lifetime = 1

    answer = resolver.resolve(fqdn)
    dns_ip = ip_address(list(answer.rrset.items.keys())[0].address)

    return dns_ip


async def delete_test_data():
    with open(CONFIG) as file_desc:
        config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    global TEST_NETWORK
    TEST_NETWORK = config['application']['network']

    dnsdb = await DnsDb.setup(config['dirserver']['dnsdb'], TEST_NETWORK)
    async with AsyncSession(dnsdb._engine) as db_session:
        stmt = delete(
            dnsdb._records_table
        ).where(
            or_(
                dnsdb._records_table.c.content == TEST_FIRST_IP,
                dnsdb._records_table.c.content == TEST_SECOND_IP,
                dnsdb._records_table.c.name ==
                f'{TEST_SERVICE_UUID}.accounts.{TEST_NETWORK}',
                dnsdb._records_table.c.name ==
                f'{TEST_SERVICE_ID}.services.{TEST_NETWORK}'
            )
        )
        await db_session.execute(stmt)

        stmt = delete(
            dnsdb._domains_table
        ).where(
            or_(
                dnsdb._domains_table.c.name == f'accounts.{TEST_NETWORK}',
                dnsdb._domains_table.c.name == f'service-{TEST_SERVICE_ID}.{TEST_NETWORK}',        # noqa: E501
                dnsdb._domains_table.c.name == f'members-{TEST_SERVICE_ID}.{TEST_NETWORK}',        # noqa: E501
            )
        )
        await db_session.execute(stmt)

    dnsdb._engine.dispose()

if __name__ == '__main__':
    unittest.main()
