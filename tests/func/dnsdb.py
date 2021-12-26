#!/usr/bin/env python3

'''
Test the DnsDB class against Postgres server for byoda.net

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license
'''

import sys
import yaml
import time
from uuid import uuid4
from ipaddress import ip_address
import unittest

import dns.resolver

from sqlalchemy import delete, or_

from byoda.util import Logger
from byoda.config import DEFAULT_NETWORK

from byoda.datatypes import IdType
from byoda.datastore.dnsdb import DnsRecordType

from byoda.datastore.dnsdb import DnsDb


CONFIG = 'tests/collateral/config-dnsdb-test.yml'
TEST_DIR = '/tmp/byoda-func-test-secrets'
NETWORK = DEFAULT_NETWORK
DNS_CACHE_PERIOD = 300

TEST_SERVICE_ID = 4294967295
TEST_UUID = 'd5c35a25-f171-4f0b-8d2f-d0808f40d0fd'
TEST_FIRST_IP = '10.255.255.254'
TEST_SECOND_IP = '10.255.255.253'
TEST_NETWORK = None


class TestDnsDb(unittest.TestCase):
    def test_dnsdb(self):
        with open(CONFIG) as file_desc:
            config = yaml.load(file_desc, Loader=yaml.SafeLoader)

        global TEST_NETWORK
        TEST_NETWORK = config['application']['network']

        dnsdb = DnsDb.setup(
            config['dirserver']['dnsdb'], TEST_NETWORK
        )

        # SERVICE
        uuid = TEST_UUID
        service_id = TEST_SERVICE_ID
        first_ip = ip_address(TEST_FIRST_IP)
        second_ip = ip_address(TEST_SECOND_IP)

        service_fqdn = dnsdb.compose_fqdn(
            None, IdType.SERVICE, service_id=service_id
        )
        self.assertEqual(
            service_fqdn, f'service.service-{str(service_id)}.{TEST_NETWORK}'
        )

        with self.assertRaises(KeyError):
            dnsdb.lookup(
                None, IdType.SERVICE, DnsRecordType.A, service_id=service_id
            )

        dnsdb.create_update(
            None, IdType.SERVICE, first_ip, service_id=service_id
        )
        self.assertEqual(
            dnsdb.lookup(
                None, IdType.SERVICE, DnsRecordType.A, service_id=service_id
            ), first_ip
        )

        dnsdb.remove(
            None, IdType.SERVICE, DnsRecordType.A, service_id=service_id
        )

        with self.assertRaises(KeyError):
            dnsdb.lookup(
                None, IdType.SERVICE, DnsRecordType.A, service_id=service_id
            )

        # MEMBER
        uuid = uuid4()
        member = dnsdb.compose_fqdn(uuid, IdType.MEMBER, service_id=service_id)
        self.assertEqual(
            member, f'{str(uuid)}.members-{service_id}.{TEST_NETWORK}'
        )

        with self.assertRaises(KeyError):
            dnsdb.lookup(
                uuid, IdType.MEMBER, DnsRecordType.A, service_id=service_id
            )

        dnsdb.create_update(
            uuid, IdType.MEMBER, first_ip, service_id=service_id
        )

        self.assertEqual(
            dnsdb.lookup(
                uuid, IdType.MEMBER, DnsRecordType.A, service_id=service_id
            ),
            first_ip
        )

        dnsdb.remove(
            uuid, IdType.MEMBER, DnsRecordType.A, service_id=service_id
        )

        with self.assertRaises(KeyError):
            dnsdb.lookup(
                uuid, IdType.MEMBER, DnsRecordType.A, service_id=service_id
            )

        # ACCOUNT: we test these last as
        uuid = uuid4()
        account = dnsdb.compose_fqdn(uuid, IdType.ACCOUNT)
        self.assertEqual(account, f'{str(uuid)}.accounts.{TEST_NETWORK}')

        with self.assertRaises(KeyError):
            dnsdb.lookup(uuid, IdType.ACCOUNT, DnsRecordType.A)

        fqdn = dnsdb.compose_fqdn(uuid, IdType.ACCOUNT)

        dnsdb.create_update(uuid, IdType.ACCOUNT, first_ip)
        self.assertEqual(
            first_ip, dnsdb.lookup(uuid, IdType.ACCOUNT, DnsRecordType.A)
        )

        dns_ip = do_dns_lookup(fqdn)
        self.assertEqual(dns_ip, first_ip)

        second_ip = ip_address(TEST_SECOND_IP)
        dnsdb.create_update(uuid, IdType.ACCOUNT, second_ip)
        self.assertEqual(
            second_ip, dnsdb.lookup(uuid, IdType.ACCOUNT, DnsRecordType.A)
        )

        time.sleep(DNS_CACHE_PERIOD + 1)

        dns_ip = do_dns_lookup(fqdn)
        self.assertEqual(dns_ip, second_ip)

        # TODO Packet and record caching of PowerDNS likely makes this test
        # fail

        # time.sleep(DNS_CACHE_PERIOD + 1)
        # with self.assertRaises(dns.resolver.NXDOMAIN):
        #    do_dns_lookup(fqdn)


def do_dns_lookup(fqdn):
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ['104.42.73.223']        # dir.byoda.net
    resolver.timeout = 1
    resolver.lifetime = 1

    answer = resolver.resolve(fqdn)
    dns_ip = ip_address(list(answer.rrset.items.keys())[0].address)

    return dns_ip


def delete_test_data():
    with open(CONFIG) as file_desc:
        config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    global TEST_NETWORK
    TEST_NETWORK = config['application']['network']

    dnsdb = DnsDb.setup(config['dirserver']['dnsdb'], TEST_NETWORK)
    with dnsdb._engine.connect() as conn:
        stmt = delete(
            dnsdb._records_table
        ).where(
            or_(
                dnsdb._records_table.c.content == TEST_FIRST_IP,
                dnsdb._records_table.c.content == TEST_SECOND_IP,
                dnsdb._records_table.c.name ==
                f'{TEST_UUID}.accounts.{TEST_NETWORK}',
                dnsdb._records_table.c.name ==
                f'{TEST_SERVICE_ID}.services.{TEST_NETWORK}'
            )
        )
        conn.execute(stmt)

        stmt = delete(
            dnsdb._domains_table
        ).where(
            or_(
                dnsdb._domains_table.c.name == f'accounts.{TEST_NETWORK}',
                dnsdb._domains_table.c.name == f'service-{TEST_SERVICE_ID}.{TEST_NETWORK}',        # noqa: E501
                dnsdb._domains_table.c.name == f'members-{TEST_SERVICE_ID}.{TEST_NETWORK}',        # noqa: E501
            )
        )
        conn.execute(stmt)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)

    delete_test_data()
    unittest.main()
